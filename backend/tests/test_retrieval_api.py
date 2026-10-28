"""检索 HTTP API 的集成测试。

使用独立临时 SQLite 和确定性的 FakeEmbeddingService，不访问真实网络或
Embedding 服务。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.documents import get_embedding_service
from app.main import app
from app.models.document import Document, DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import EmbeddingWrite, save_embeddings

SessionFactory = async_sessionmaker[AsyncSession]


class FakeEmbeddingService(EmbeddingService):
    """返回固定查询向量的测试替身。"""

    def __init__(
        self,
        *,
        dimension: int = 4,
        model: str = "fake-embedding",
        query_vector: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
    ) -> None:
        self._dimension = dimension
        self._model = model
        self._query_vector = list(query_vector)
        self.queries: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(self._query_vector) for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return list(self._query_vector)


def _seed_document(
    session_factory: SessionFactory,
    *,
    filename: str = "检索测试.txt",
    texts: Sequence[str] = ("第一段考勤内容。", "第二段请假内容。"),
    vectors: Sequence[Sequence[float]] | None = None,
    model: str | None = "fake-embedding",
) -> tuple[int, list[int]]:
    """直接创建文档、文本块和可选向量，返回文档 ID 与文本块 ID。"""

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

            if vectors is not None:
                items = [
                    EmbeddingWrite(
                        chunk_id=chunk.id,
                        vector=list(vector),
                        dimension=len(vector),
                        model=model,
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
                await save_embeddings(session, items)
            else:
                await session.commit()

            return document.id, [chunk.id for chunk in chunks]

    return asyncio.run(run())


@contextmanager
def _override_service(
    service: EmbeddingService | None,
) -> Iterator[None]:
    """临时覆盖 Embedding 依赖，结束后恢复。"""
    app.dependency_overrides[get_embedding_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_embedding_service, None)


def _search(
    client: TestClient,
    payload: dict[str, Any],
) -> Any:
    return client.post("/api/v1/retrieval/search", json=payload)


def test_search_success_returns_hits_without_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, chunk_ids = _seed_document(
        sqlite_session_factory,
        vectors=([1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]),
    )
    fake = FakeEmbeddingService()

    with _override_service(fake):
        response = _search(
            db_client,
            {"query": "  公司的考勤制度  ", "top_k": 5},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "公司的考勤制度"
    assert len(body["hits"]) == 2
    assert fake.queries == ["公司的考勤制度"]

    first = body["hits"][0]
    assert set(first) == {
        "chunk_id",
        "document_id",
        "chunk_index",
        "text",
        "score",
        "model",
        "dimension",
    }
    assert first["chunk_id"] == chunk_ids[0]
    assert first["document_id"] == document_id
    assert first["chunk_index"] == 0
    assert first["score"] == pytest.approx(1.0)
    assert first["model"] == "fake-embedding"
    assert first["dimension"] == 4
    assert "vector" not in response.text
    assert "api_key" not in response.text


def test_search_respects_top_k_and_score_order(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("最相关。", "次相关。", "不相关。"),
        vectors=(
            [1.0, 0.0, 0.0, 0.0],
            [0.8, 0.6, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ),
    )
    fake = FakeEmbeddingService()

    with _override_service(fake):
        response = _search(db_client, {"query": "考勤", "top_k": 2})

    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 2
    assert [hit["score"] for hit in hits] == pytest.approx([1.0, 0.8])
    assert hits[0]["text"] == "最相关。"
    assert hits[1]["text"] == "次相关。"


def test_search_filters_by_document_id(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        filename="文档一.txt",
        texts=("文档一内容。",),
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    target_document_id, _ = _seed_document(
        sqlite_session_factory,
        filename="文档二.txt",
        texts=("文档二内容。",),
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    fake = FakeEmbeddingService()

    with _override_service(fake):
        response = _search(
            db_client,
            {"query": "内容", "document_id": target_document_id},
        )

    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 1
    assert hits[0]["document_id"] == target_document_id


def test_search_filters_by_min_score(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("相关内容。", "弱相关内容。"),
        vectors=(
            [1.0, 0.0, 0.0, 0.0],
            [0.6, 0.8, 0.0, 0.0],
        ),
    )
    fake = FakeEmbeddingService()

    with _override_service(fake):
        response = _search(
            db_client,
            {"query": "内容", "min_score": 0.9},
        )

    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 1
    assert hits[0]["text"] == "相关内容。"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("top_k", 0),
        ("top_k", 101),
        ("top_k", True),
        ("document_id", 0),
        ("document_id", -1),
        ("document_id", True),
        ("min_score", -1.1),
        ("min_score", 1.1),
        ("min_score", True),
    ],
)
def test_search_rejects_invalid_parameters(
    db_client: TestClient,
    field: str,
    value: int | float,
) -> None:
    response = _search(db_client, {"query": "考勤", field: value})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(
    db_client: TestClient,
    query: str,
) -> None:
    response = _search(db_client, {"query": query})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_query"


def test_search_returns_503_when_embedding_is_not_configured(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("考勤内容。",),
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )

    with _override_service(None):
        response = _search(db_client, {"query": "考勤"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "embedding_not_configured"
    assert "api_key" not in response.text.lower()


def test_search_without_matching_vectors_returns_empty_hits(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        texts=("尚未向量化的文本块。",),
        vectors=None,
    )
    fake = FakeEmbeddingService()

    with _override_service(fake):
        response = _search(db_client, {"query": "考勤"})

    assert response.status_code == 200
    assert response.json()["hits"] == []


def test_search_openapi_contains_route(db_client: TestClient) -> None:
    response = db_client.get("/openapi.json")

    assert response.status_code == 200
    path = response.json()["paths"]["/api/v1/retrieval/search"]
    assert "post" in path
    request_schema = path["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert request_schema["$ref"].endswith("/RetrievalSearchRequest")
