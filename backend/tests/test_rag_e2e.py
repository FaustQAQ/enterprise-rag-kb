"""使用隔离 SQLite 和 Fake Embedding 的 RAG 端到端验收测试。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.documents import get_embedding_service
from app.main import app
from app.models.document import DocumentChunkEmbedding
from app.services.embedding_service import EmbeddingProviderError, EmbeddingService
from app.services.vector_store import get_embeddings_for_document

SessionFactory = async_sessionmaker[AsyncSession]


class E2EFakeEmbeddingService(EmbeddingService):
    """可控查询/文档向量和模型标识的测试服务。"""

    def __init__(
        self,
        *,
        dimension: int = 4,
        model: str = "e2e-model-v1",
        document_vector: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        query_vector: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        error: Exception | None = None,
        document_vectors: Sequence[Sequence[float]] | None = None,
    ) -> None:
        self._dimension = dimension
        self.model_name = model
        self.document_vector = list(document_vector)
        self.query_vector = list(query_vector)
        self.error = error
        self.document_vectors = (
            [list(vector) for vector in document_vectors]
            if document_vectors is not None
            else None
        )
        self.document_calls: list[list[str]] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        return self.model_name

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        if self.error is not None:
            raise self.error
        if self.document_vectors is not None:
            return [list(vector) for vector in self.document_vectors]
        return [list(self.document_vector) for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.error is not None:
            raise self.error
        return list(self.query_vector)


@contextmanager
def _embedding_override(service: EmbeddingService) -> Iterator[None]:
    app.dependency_overrides[get_embedding_service] = lambda: service
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_embedding_service, None)


def _upload(client: TestClient, *, filename: str = "企业制度.txt") -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents",
        files={
            "file": (
                filename,
                "员工每日应按制度打卡。迟到需要说明原因。请遵守考勤管理要求。".encode(
                    "utf-8"
                ),
                "text/plain",
            )
        },
        data={"chunk_size": "18", "chunk_overlap": "0"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["chunk_count"] == len(payload["chunks"])
    assert payload["chunk_count"] >= 2
    return payload


def _embed(
    client: TestClient,
    document_id: int,
    service: EmbeddingService,
) -> dict[str, Any]:
    with _embedding_override(service):
        response = client.post(f"/api/v1/documents/{document_id}/embed")
    assert response.status_code == 200, response.text
    return response.json()


async def _read_embeddings(
    session_factory: SessionFactory,
    document_id: int,
) -> list[tuple[int, list[float], int, str | None]]:
    async with session_factory() as session:
        stored = await get_embeddings_for_document(session, document_id)
        return [
            (item.chunk_id, item.vector, item.dimension, item.model)
            for item in stored
        ]


def _stored_embeddings(
    session_factory: SessionFactory,
    document_id: int,
) -> list[tuple[int, list[float], int, str | None]]:
    return asyncio.run(_read_embeddings(session_factory, document_id))


def test_end_to_end_upload_embed_retrieve_and_chat(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    service = E2EFakeEmbeddingService()
    document = _upload(db_client)
    document_id = document["id"]
    chunk_ids = [chunk["id"] for chunk in document["chunks"]]
    embed_response = _embed(db_client, document_id, service)
    assert embed_response["embedded_count"] == document["chunk_count"]
    assert len(_stored_embeddings(sqlite_session_factory, document_id)) == len(chunk_ids)

    with _embedding_override(service):
        retrieval_response = db_client.post(
            "/api/v1/retrieval/search",
            json={"query": "考勤管理要求", "document_id": document_id, "top_k": 10},
        )
        chat_response = db_client.post(
            "/api/v1/chat",
            json={"question": "考勤管理要求", "document_id": document_id, "top_k": 10},
        )

    assert retrieval_response.status_code == 200, retrieval_response.text
    retrieval_hits = retrieval_response.json()["hits"]
    assert retrieval_hits
    assert all(hit["document_id"] == document_id for hit in retrieval_hits)
    assert [hit["chunk_id"] for hit in retrieval_hits] == chunk_ids
    assert [
        hit["text"] for hit in retrieval_hits
    ] == [chunk["text"] for chunk in document["chunks"]]

    assert chat_response.status_code == 200, chat_response.text
    chat_body = chat_response.json()
    assert [source["chunk_id"] for source in chat_body["sources"]] == [
        hit["chunk_id"] for hit in retrieval_hits
    ]
    assert all(source["document_id"] == document_id for source in chat_body["sources"])
    assert all(source["filename"] == "企业制度.txt" for source in chat_body["sources"])
    assert [source["text"] for source in chat_body["sources"]] == [
        hit["text"] for hit in retrieval_hits
    ]


def test_chat_without_compatible_vectors_returns_empty_sources_and_refusal(
    db_client: TestClient,
) -> None:
    service = E2EFakeEmbeddingService(model="e2e-model-v1")
    document = _upload(db_client, filename="无兼容向量.txt")
    _embed(db_client, document["id"], service)

    service.model_name = "unmatched-model"
    with _embedding_override(service):
        response = db_client.post(
            "/api/v1/chat",
            json={"question": "完全不同的查询", "document_id": document["id"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"] == []
    assert "无法根据提供的知识库上下文回答" in body["answer"]


def test_reembedding_same_document_updates_without_duplicate_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document = _upload(db_client, filename="重复向量化.txt")
    document_id = document["id"]
    chunk_ids = [chunk["id"] for chunk in document["chunks"]]

    first = E2EFakeEmbeddingService(
        model="e2e-model-v1",
        document_vector=(1.0, 0.0, 0.0, 0.0),
    )
    second = E2EFakeEmbeddingService(
        model="e2e-model-v2",
        document_vector=(0.0, 1.0, 0.0, 0.0),
    )
    _embed(db_client, document_id, first)
    _embed(db_client, document_id, second)

    stored = _stored_embeddings(sqlite_session_factory, document_id)
    assert len(stored) == len(chunk_ids)
    assert [item[0] for item in stored] == chunk_ids
    assert all(item[1] == [0.0, 1.0, 0.0, 0.0] for item in stored)
    assert all(item[2] == 4 and item[3] == "e2e-model-v2" for item in stored)

    async def count_rows() -> int:
        async with sqlite_session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(DocumentChunkEmbedding)
            )
            return int(count or 0)

    assert asyncio.run(count_rows()) == len(chunk_ids)


@pytest.mark.parametrize(
    "failure_service",
    [
        E2EFakeEmbeddingService(
            model="e2e-failing-provider",
            error=EmbeddingProviderError("simulated provider failure"),
        ),
        E2EFakeEmbeddingService(
            model="e2e-count-mismatch",
            document_vectors=[[9.0, 9.0, 9.0, 9.0]],
        ),
        E2EFakeEmbeddingService(
            model="e2e-dimension-error",
            document_vector=(9.0, 9.0, 9.0),
        ),
    ],
)
def test_reembedding_failure_preserves_old_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
    failure_service: E2EFakeEmbeddingService,
) -> None:
    document = _upload(db_client, filename="失败保护.txt")
    document_id = document["id"]
    old_service = E2EFakeEmbeddingService(
        model="e2e-old-model",
        document_vector=(1.0, 2.0, 3.0, 4.0),
    )
    _embed(db_client, document_id, old_service)
    old_vectors = _stored_embeddings(sqlite_session_factory, document_id)

    with _embedding_override(failure_service):
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")

    assert response.status_code == 502
    assert _stored_embeddings(sqlite_session_factory, document_id) == old_vectors


def test_successful_reembedding_replaces_old_vectors_once(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document = _upload(db_client, filename="成功覆盖.txt")
    document_id = document["id"]
    old_service = E2EFakeEmbeddingService(
        model="e2e-old-model",
        document_vector=(1.0, 0.0, 0.0, 0.0),
    )
    new_service = E2EFakeEmbeddingService(
        model="e2e-new-model",
        document_vector=(0.0, 0.0, 1.0, 0.0),
    )
    _embed(db_client, document_id, old_service)
    _embed(db_client, document_id, new_service)

    stored = _stored_embeddings(sqlite_session_factory, document_id)
    assert len(stored) == document["chunk_count"]
    assert all(item[1] == [0.0, 0.0, 1.0, 0.0] for item in stored)
    assert all(item[2] == 4 and item[3] == "e2e-new-model" for item in stored)


def test_retrieval_isolates_models_and_dimensions_end_to_end(
    db_client: TestClient,
) -> None:
    model_a = E2EFakeEmbeddingService(model="model-a", dimension=4)
    model_b = E2EFakeEmbeddingService(model="model-b", dimension=4)
    model_a_dim3 = E2EFakeEmbeddingService(
        model="model-a",
        dimension=3,
        document_vector=(1.0, 0.0, 0.0),
        query_vector=(1.0, 0.0, 0.0),
    )

    document_a = _upload(db_client, filename="模型A.txt")
    document_b = _upload(db_client, filename="模型B.txt")
    document_a_dim3 = _upload(db_client, filename="模型A三维.txt")
    _embed(db_client, document_a["id"], model_a)
    _embed(db_client, document_b["id"], model_b)
    _embed(db_client, document_a_dim3["id"], model_a_dim3)

    with _embedding_override(model_a):
        response_a = db_client.post("/api/v1/retrieval/search", json={"query": "查询"})
    with _embedding_override(model_b):
        response_b = db_client.post("/api/v1/retrieval/search", json={"query": "查询"})
    with _embedding_override(model_a_dim3):
        response_a_dim3 = db_client.post(
            "/api/v1/retrieval/search", json={"query": "查询"}
        )
    no_match = E2EFakeEmbeddingService(model="model-missing", dimension=4)
    with _embedding_override(no_match):
        response_missing = db_client.post(
            "/api/v1/retrieval/search", json={"query": "查询"}
        )

    assert response_a.status_code == 200
    assert {hit["document_id"] for hit in response_a.json()["hits"]} == {
        document_a["id"]
    }
    assert response_b.status_code == 200
    assert {hit["document_id"] for hit in response_b.json()["hits"]} == {
        document_b["id"]
    }
    assert response_a_dim3.status_code == 200
    assert {hit["document_id"] for hit in response_a_dim3.json()["hits"]} == {
        document_a_dim3["id"]
    }
    assert response_missing.status_code == 200
    assert response_missing.json()["hits"] == []
