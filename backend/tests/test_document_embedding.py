"""文档向量化编排与 API 的集成测试。

所有外部 Embedding 调用都由 FakeEmbeddingService 模拟，不依赖网络或真实 API
密钥；数据库使用每个测试独立的临时 SQLite 文件。
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.documents import get_embedding_service
from app.main import app
from app.models.document import Document, DocumentChunkEmbedding
from app.services.document_store import save_document
from app.services.embedding_service import (
    EmbeddingProviderError,
    EmbeddingService,
    EmbeddingTimeoutError,
)
from app.services.vector_store import get_embeddings_for_document

SessionFactory = async_sessionmaker[AsyncSession]


class FakeEmbeddingService(EmbeddingService):
    """确定性的测试替身，不生成生产向量。"""

    def __init__(
        self,
        *,
        dimension: int = 4,
        vectors: Sequence[Sequence[Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._dimension = dimension
        self._vectors = vectors
        self._error = error
        self.calls: list[list[str]] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        return "fake-embedding"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._error is not None:
            raise self._error
        if self._vectors is not None:
            return [list(vector) for vector in self._vectors]
        return [
            [float(position), 0.25, -0.5, 1.0]
            for position in range(len(texts))
        ]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return list(vectors[0])


def _seed_document(
    session_factory: SessionFactory,
    *,
    text: str = "第一段内容。\n\n第二段内容。",
) -> tuple[int, int]:
    """保存文档，返回 ID 和文本块数量。"""

    async def run() -> tuple[int, int]:
        async with session_factory() as session:
            document = await save_document(
                session,
                filename="待向量化.txt",
                file_type="txt",
                text=text,
                chunk_size=12,
                chunk_overlap=0,
            )
            return document.id, len(document.chunks)

    return asyncio.run(run())


def _seed_empty_document(session_factory: SessionFactory) -> int:
    """直接创建没有文本块的文档，用于测试业务错误。"""

    async def run() -> int:
        async with session_factory() as session:
            document = Document(
                filename="empty.txt",
                file_type="txt",
                character_count=1,
                status="processed",
            )
            session.add(document)
            await session.commit()
            return document.id

    return asyncio.run(run())


def _count_vectors(session_factory: SessionFactory) -> int:
    async def run() -> int:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(DocumentChunkEmbedding)
            )
            return int(count or 0)

    return asyncio.run(run())


def _override_service(service: EmbeddingService | None) -> None:
    app.dependency_overrides[get_embedding_service] = lambda: service


def _clear_override() -> None:
    app.dependency_overrides.pop(get_embedding_service, None)


def test_embed_document_api_saves_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, chunk_count = _seed_document(sqlite_session_factory)
    fake = FakeEmbeddingService()

    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["chunk_count"] == chunk_count
    assert payload["embedded_count"] == chunk_count
    assert payload["dimension"] == 4
    assert payload["model"] == "fake-embedding"
    assert payload["status"] == "completed"
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == chunk_count

    async def read_vectors() -> list[list[float]]:
        async with sqlite_session_factory() as session:
            stored = await get_embeddings_for_document(session, document_id)
            assert len(stored) == chunk_count
            assert all(item.dimension == 4 for item in stored)
            assert all(item.model == "fake-embedding" for item in stored)
            return [item.vector for item in stored]

    vectors = asyncio.run(read_vectors())
    assert len(vectors) == chunk_count
    assert all(len(vector) == 4 for vector in vectors)


def test_embed_api_returns_404_for_missing_document(
    db_client: TestClient,
) -> None:
    _override_service(FakeEmbeddingService())
    try:
        response = db_client.post("/api/v1/documents/999999/embed")
    finally:
        _clear_override()

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "document_not_found"
    assert "999999" not in body["error"]["message"]


def test_embed_api_rejects_document_without_chunks(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id = _seed_empty_document(sqlite_session_factory)
    _override_service(FakeEmbeddingService())
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "document_has_no_chunks"
    assert _count_vectors(sqlite_session_factory) == 0


def test_embed_api_unconfigured_service(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, _ = _seed_document(sqlite_session_factory)
    _override_service(None)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "embedding_not_configured"
    assert _count_vectors(sqlite_session_factory) == 0


def test_embed_api_provider_failure_does_not_write(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, _ = _seed_document(sqlite_session_factory)
    fake = FakeEmbeddingService(error=EmbeddingProviderError("upstream failed"))
    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "embedding_provider_error"
    assert _count_vectors(sqlite_session_factory) == 0


def test_embed_api_timeout_does_not_write(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, _ = _seed_document(sqlite_session_factory)
    fake = FakeEmbeddingService(error=EmbeddingTimeoutError("timeout"))
    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "embedding_timeout"
    assert _count_vectors(sqlite_session_factory) == 0


def test_embed_api_rejects_count_mismatch(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, chunk_count = _seed_document(sqlite_session_factory)
    # 故意少返回一条向量。
    vectors = [[1.0, 2.0, 3.0, 4.0] for _ in range(max(0, chunk_count - 1))]
    fake = FakeEmbeddingService(vectors=vectors)
    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_embedding_response"
    assert _count_vectors(sqlite_session_factory) == 0


@pytest.mark.parametrize(
    "bad_vector",
    [
        [],
        [1.0, 2.0, 3.0],
        [math.nan, 2.0, 3.0, 4.0],
        [math.inf, 2.0, 3.0, 4.0],
        ["a", 2.0, 3.0, 4.0],
    ],
)
def test_embed_api_rejects_invalid_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
    bad_vector: list[Any],
) -> None:
    document_id, chunk_count = _seed_document(sqlite_session_factory)
    vectors = [bad_vector for _ in range(chunk_count)]
    fake = FakeEmbeddingService(vectors=vectors)
    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_embedding_response"
    assert _count_vectors(sqlite_session_factory) == 0


def test_embed_api_rejects_dimension_mismatch(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, chunk_count = _seed_document(sqlite_session_factory)
    vectors = [[1.0, 2.0, 3.0] for _ in range(chunk_count)]
    fake = FakeEmbeddingService(vectors=vectors)
    _override_service(fake)
    try:
        response = db_client.post(f"/api/v1/documents/{document_id}/embed")
    finally:
        _clear_override()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_embedding_response"
    assert _count_vectors(sqlite_session_factory) == 0


def test_delete_document_api_removes_vectors(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id, _ = _seed_document(sqlite_session_factory)
    _override_service(FakeEmbeddingService())
    try:
        embed_response = db_client.post(
            f"/api/v1/documents/{document_id}/embed"
        )
    finally:
        _clear_override()
    assert embed_response.status_code == 200
    assert _count_vectors(sqlite_session_factory) > 0

    delete_response = db_client.delete(f"/api/v1/documents/{document_id}")
    assert delete_response.status_code == 200
    assert _count_vectors(sqlite_session_factory) == 0


def test_openapi_contains_embed_route(db_client: TestClient) -> None:
    response = db_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/documents/{document_id}/embed" in paths
    assert "post" in paths["/api/v1/documents/{document_id}/embed"]
