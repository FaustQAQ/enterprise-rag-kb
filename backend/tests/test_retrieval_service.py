"""检索服务的单元测试。

所有测试使用临时 SQLite 和确定性的 FakeEmbeddingService，不访问网络或真实
Embedding 服务；不依赖检索 HTTP API。
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import VectorStoreError
from app.models.document import Document, DocumentChunk
from app.services.embedding_service import (
    EmbeddingNotConfiguredError,
    EmbeddingProviderError,
    EmbeddingService,
)
from app.services.retrieval import (
    RetrievalError,
    RetrievedChunk,
    cosine_similarity,
    search_chunks,
    search_similar_chunks,
)
from app.services.vector_store import EmbeddingWrite, save_embeddings

SessionFactory = async_sessionmaker[AsyncSession]


class FakeEmbeddingService(EmbeddingService):
    """只返回预设向量的测试替身。"""

    def __init__(
        self,
        *,
        dimension: int = 4,
        model: str | None = "fake-embedding",
        query_vector: Sequence[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._dimension = dimension
        self._model = model
        self._query_vector = (
            list(query_vector)
            if query_vector is not None
            else [1.0, 0.0, 0.0, 0.0]
        )
        self._error = error
        self.queries: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self._error is not None:
            raise self._error
        return [list(self._query_vector) for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self._error is not None:
            raise self._error
        return list(self._query_vector)


def _seed_document(
    session_factory: SessionFactory,
    *,
    filename: str = "检索测试.txt",
    texts: Sequence[str] = ("第一段。", "第二段。"),
    vectors: Sequence[Sequence[float]] | None = None,
    models: Sequence[str | None] | None = None,
) -> tuple[int, list[int]]:
    """直接创建文档和文本块；可选写入测试向量。"""

    async def run() -> tuple[int, list[int]]:
        async with session_factory() as session:
            document = Document(
                filename=filename,
                file_type="txt",
                character_count=sum(len(text) for text in texts),
                status="processed",
            )
            session.add(document)
            await session.flush()

            chunks: list[DocumentChunk] = []
            offset = 0
            for index, text in enumerate(texts):
                chunk = DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    text=text,
                    character_count=len(text),
                    start_index=offset,
                    end_index=offset + len(text),
                )
                session.add(chunk)
                chunks.append(chunk)
                offset += len(text)
            await session.flush()

            if vectors:
                normalized_models: Sequence[str | None]
                if models is None:
                    normalized_models = ["fake-embedding"] * len(vectors)
                else:
                    normalized_models = models
                items = [
                    EmbeddingWrite(
                        chunk_id=chunk.id,
                        vector=list(vector),
                        dimension=len(vector),
                        model=model,
                    )
                    for chunk, vector, model in zip(
                        chunks,
                        vectors,
                        normalized_models,
                        strict=True,
                    )
                ]
                await save_embeddings(session, items)
            else:
                await session.commit()

            return document.id, [chunk.id for chunk in chunks]

    return asyncio.run(run())


def _search(
    session_factory: SessionFactory,
    query_vector: Sequence[float],
    **kwargs: Any,
) -> list[RetrievedChunk]:
    async def run() -> list[RetrievedChunk]:
        async with session_factory() as session:
            return await search_similar_chunks(
                session,
                query_vector,
                **kwargs,
            )

    return asyncio.run(run())


def _search_text(
    session_factory: SessionFactory,
    query: str,
    service: EmbeddingService | None,
    **kwargs: Any,
) -> list[RetrievedChunk]:
    async def run() -> list[RetrievedChunk]:
        async with session_factory() as session:
            return await search_chunks(
                session,
                query,
                embedding_service=service,
                **kwargs,
            )

    return asyncio.run(run())


def test_cosine_similarity_normal() -> None:
    assert cosine_similarity([1.0, 2.0], [3.0, 4.0]) == pytest.approx(0.98386991)


def test_cosine_similarity_same_direction_is_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_opposite_is_negative_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_cosine_similarity_zero_vector_is_zero() -> None:
    """零向量没有方向，明确返回 0.0，不能发生除零。"""
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


@pytest.mark.parametrize(
    ("query_vector", "chunk_vector"),
    [
        ([], [1.0]),
        ([1.0], []),
        ([1.0, 2.0], [1.0]),
        ([1.0, 2.0], [1.0, 2.0, 3.0]),
        ([1.0, math.nan], [1.0, 0.0]),
        ([1.0, math.inf], [1.0, 0.0]),
        ([True, 0.0], [1.0, 0.0]),
        (["1", 0.0], [1.0, 0.0]),
        ("not-a-vector", [1.0]),
        (None, [1.0]),
    ],
)
def test_cosine_similarity_rejects_invalid_vectors(
    query_vector: object,
    chunk_vector: object,
) -> None:
    with pytest.raises(VectorStoreError):
        cosine_similarity(query_vector, chunk_vector)  # type: ignore[arg-type]


def test_search_deduplicates_exact_duplicate_documents_but_keeps_distinct_names(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        filename="same.txt",
        texts=("相同正文",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )
    _seed_document(
        sqlite_session_factory,
        filename="same.txt",
        texts=("相同正文",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )
    _seed_document(
        sqlite_session_factory,
        filename="other.txt",
        texts=("相同正文",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], top_k=10, model="m")

    assert len(hits) == 2
    assert len({hit.document_id for hit in hits}) == 2
    assert {hit.chunk_index for hit in hits} == {0}


def test_search_top_k_and_score_order(sqlite_session_factory: SessionFactory) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("最相似", "次相似", "正交"),
        vectors=(
            [1.0, 0.0],
            [0.8, 0.6],
            [0.0, 1.0],
        ),
        models=("m", "m", "m"),
    )

    hits = _search(
        sqlite_session_factory,
        [1.0, 0.0],
        top_k=2,
        model="m",
    )

    assert [hit.text for hit in hits] == ["最相似", "次相似"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(0.8)


def test_search_result_count_is_limited(sqlite_session_factory: SessionFactory) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("一", "二", "三"),
        vectors=(
            [1.0, 0.0],
            [1.0, 0.0],
            [1.0, 0.0],
        ),
        models=("m", "m", "m"),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], top_k=1, model="m")
    assert len(hits) == 1


def test_search_ties_are_stable(sqlite_session_factory: SessionFactory) -> None:
    first_document_id, first_chunks = _seed_document(
        sqlite_session_factory,
        filename="first.txt",
        texts=("a", "b"),
        vectors=([1.0, 0.0], [1.0, 0.0]),
        models=("m", "m"),
    )
    second_document_id, second_chunks = _seed_document(
        sqlite_session_factory,
        filename="second.txt",
        texts=("c",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], top_k=3, model="m")

    assert [hit.chunk_id for hit in hits] == [
        first_chunks[0],
        first_chunks[1],
        second_chunks[0],
    ]
    assert [hit.document_id for hit in hits] == [
        first_document_id,
        first_document_id,
        second_document_id,
    ]


def test_search_filters_by_document_id(sqlite_session_factory: SessionFactory) -> None:
    first_document_id, _ = _seed_document(
        sqlite_session_factory,
        filename="first.txt",
        texts=("first",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )
    second_document_id, _ = _seed_document(
        sqlite_session_factory,
        filename="second.txt",
        texts=("second",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )

    hits = _search(
        sqlite_session_factory,
        [1.0, 0.0],
        model="m",
        document_id=second_document_id,
    )

    assert [hit.document_id for hit in hits] == [second_document_id]
    assert first_document_id not in [hit.document_id for hit in hits]


def test_search_filters_by_min_score(sqlite_session_factory: SessionFactory) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("same", "orthogonal"),
        vectors=([1.0, 0.0], [0.0, 1.0]),
        models=("m", "m"),
    )

    hits = _search(
        sqlite_session_factory,
        [1.0, 0.0],
        model="m",
        min_score=0.5,
    )

    assert [hit.text for hit in hits] == ["same"]


def test_search_no_vectors_returns_empty(sqlite_session_factory: SessionFactory) -> None:
    _seed_document(sqlite_session_factory, vectors=None)

    assert _search(sqlite_session_factory, [1.0, 0.0], model="m") == []


def test_search_no_matching_min_score_returns_empty(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("orthogonal",),
        vectors=([0.0, 1.0],),
        models=("m",),
    )

    assert (
        _search(
            sqlite_session_factory,
            [1.0, 0.0],
            model="m",
            min_score=0.5,
        )
        == []
    )


def test_search_does_not_mix_different_models(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        filename="model-a.txt",
        texts=("a",),
        vectors=([1.0, 0.0],),
        models=("model-a",),
    )
    _seed_document(
        sqlite_session_factory,
        filename="model-b.txt",
        texts=("b",),
        vectors=([1.0, 0.0],),
        models=("model-b",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], model="model-a")

    assert len(hits) == 1
    assert hits[0].model == "model-a"


def test_search_without_model_only_uses_null_model_vectors(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        filename="null-model.txt",
        texts=("null",),
        vectors=([1.0, 0.0],),
        models=(None,),
    )
    _seed_document(
        sqlite_session_factory,
        filename="named-model.txt",
        texts=("named",),
        vectors=([1.0, 0.0],),
        models=("model-a",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], model=None)

    assert len(hits) == 1
    assert hits[0].model is None
    assert hits[0].text == "null"


def test_search_only_compares_compatible_dimensions(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        filename="dimension-2.txt",
        texts=("two",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )
    _seed_document(
        sqlite_session_factory,
        filename="dimension-4.txt",
        texts=("four",),
        vectors=([1.0, 0.0, 0.0, 0.0],),
        models=("m",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], model="m")

    assert len(hits) == 1
    assert hits[0].text == "two"
    assert hits[0].dimension == 2


@pytest.mark.parametrize("top_k", [0, -1, 101, 1.5, True])
def test_search_rejects_invalid_top_k(
    sqlite_session_factory: SessionFactory,
    top_k: object,
) -> None:
    with pytest.raises(RetrievalError):
        _search(sqlite_session_factory, [1.0, 0.0], top_k=top_k)  # type: ignore[arg-type]


@pytest.mark.parametrize("min_score", [-1.01, 1.01, math.nan, math.inf, True, "0.5"])
def test_search_rejects_invalid_min_score(
    sqlite_session_factory: SessionFactory,
    min_score: object,
) -> None:
    with pytest.raises(RetrievalError):
        _search(
            sqlite_session_factory,
            [1.0, 0.0],
            min_score=min_score,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("document_id", [0, -1, True, 1.5, "1"])
def test_search_rejects_invalid_document_id(
    sqlite_session_factory: SessionFactory,
    document_id: object,
) -> None:
    with pytest.raises(RetrievalError):
        _search(
            sqlite_session_factory,
            [1.0, 0.0],
            document_id=document_id,  # type: ignore[arg-type]
        )


def test_search_returns_no_raw_vectors(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("text",),
        vectors=([1.0, 0.0],),
        models=("m",),
    )

    hits = _search(sqlite_session_factory, [1.0, 0.0], model="m")

    assert hits
    assert not hasattr(hits[0], "vector")


def test_search_database_error_is_mapped() -> None:
    class FailingSession:
        rolled_back = False

        async def execute(self, _statement: object) -> object:
            raise OperationalError(
                "SELECT 1",
                {},
                RuntimeError("database down"),
            )

        async def rollback(self) -> None:
            self.rolled_back = True

    session = FailingSession()

    async def run() -> None:
        await search_similar_chunks(session, [1.0, 0.0])  # type: ignore[arg-type]

    with pytest.raises(RetrievalError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.code == "database_unavailable"
    assert exc_info.value.status_code == 503
    assert session.rolled_back is True


def test_search_chunks_uses_query_embedding(
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("匹配文本",),
        vectors=([1.0, 0.0, 0.0, 0.0],),
        models=("fake-embedding",),
    )
    service = FakeEmbeddingService()

    hits = _search_text(sqlite_session_factory, "  查询文本  ", service)

    assert [hit.text for hit in hits] == ["匹配文本"]
    assert service.queries == ["查询文本"]


def test_search_chunks_rejects_empty_query(
    sqlite_session_factory: SessionFactory,
) -> None:
    service = FakeEmbeddingService()

    with pytest.raises(RetrievalError) as exc_info:
        _search_text(sqlite_session_factory, "  \n\t ", service)

    assert exc_info.value.code == "empty_query"
    assert service.queries == []


def test_search_chunks_requires_configured_service(
    sqlite_session_factory: SessionFactory,
) -> None:
    with pytest.raises(RetrievalError) as exc_info:
        _search_text(sqlite_session_factory, "query", None)

    assert exc_info.value.code == "embedding_not_configured"
    assert exc_info.value.status_code == 503


def test_search_chunks_rejects_query_vector_dimension_mismatch(
    sqlite_session_factory: SessionFactory,
) -> None:
    service = FakeEmbeddingService(
        dimension=4,
        query_vector=[1.0, 0.0, 0.0],
    )

    with pytest.raises(RetrievalError) as exc_info:
        _search_text(sqlite_session_factory, "query", service)

    assert exc_info.value.code == "invalid_embedding_response"
    assert exc_info.value.status_code == 502


def test_search_chunks_maps_provider_failure(
    sqlite_session_factory: SessionFactory,
) -> None:
    service = FakeEmbeddingService(
        error=EmbeddingProviderError("provider unavailable")
    )

    with pytest.raises(RetrievalError) as exc_info:
        _search_text(sqlite_session_factory, "query", service)

    assert exc_info.value.code == "embedding_provider_error"
    assert exc_info.value.status_code == 502


def test_search_chunks_maps_not_configured_embedding(
    sqlite_session_factory: SessionFactory,
) -> None:
    service = FakeEmbeddingService(
        error=EmbeddingNotConfiguredError("not configured")
    )

    with pytest.raises(RetrievalError) as exc_info:
        _search_text(sqlite_session_factory, "query", service)

    assert exc_info.value.code == "embedding_not_configured"
    assert exc_info.value.status_code == 503
