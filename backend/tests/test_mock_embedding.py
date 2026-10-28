"""本地 Mock Embedding 的行为与检索集成测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services import embedding_service as embedding_module
from app.services.embedding_service import (
    EmbeddingInputError,
    EmbeddingNotConfiguredError,
    EmbeddingService,
    MockEmbeddingService,
    create_embedding_service,
)
from app.services.retrieval import RetrievalError, search_chunks
from app.services.vector_store import EmbeddingWrite, save_embeddings
from app.models.document import Document, DocumentChunk

SessionFactory = async_sessionmaker[AsyncSession]


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "development",
        "embedding_mock_enabled": False,
        "embedding_provider": None,
        "embedding_api_key": None,
        "embedding_model": None,
        "embedding_dimension": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_mock_embedding_is_disabled_by_default() -> None:
    settings = _settings()

    assert settings.embedding_mock_enabled is False
    with pytest.raises(EmbeddingNotConfiguredError):
        create_embedding_service(settings)


def test_development_can_explicitly_create_mock_embedding() -> None:
    service = create_embedding_service(
        _settings(embedding_mock_enabled=True, embedding_dimension=16)
    )

    assert isinstance(service, MockEmbeddingService)
    assert isinstance(service, EmbeddingService)
    assert service.dimension == 16
    assert service.model == MockEmbeddingService.MODEL_NAME


def test_production_rejects_explicit_mock_embedding() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="production"):
        create_embedding_service(
            _settings(environment="production", embedding_mock_enabled=True)
        )


def test_mock_vectors_are_deterministic_and_compatible() -> None:
    service = MockEmbeddingService(dimension=32)

    async def run() -> tuple[list[float], list[list[float]]]:
        return (
            await service.embed_query("企业知识库"),
            await service.embed_documents(["企业知识库", "另一个文本"]),
        )

    query_vector, document_vectors = asyncio.run(run())

    assert query_vector == document_vectors[0]
    assert len(query_vector) == service.dimension
    assert all(len(vector) == service.dimension for vector in document_vectors)
    assert all(isinstance(value, float) for value in query_vector)
    assert service.model == MockEmbeddingService.MODEL_NAME


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("query", ""),
        ("query", " \n\t "),
        ("query", 123),
        ("documents", [""]),
        ("documents", ["  "]),
        ("documents", ["ok", 123]),
        ("documents", "not-a-sequence"),
    ],
)
def test_mock_embedding_validates_inputs(method: str, value: Any) -> None:
    service = MockEmbeddingService()

    async def run() -> None:
        if method == "query":
            await service.embed_query(value)  # type: ignore[arg-type]
        else:
            await service.embed_documents(value)  # type: ignore[arg-type]

    with pytest.raises(EmbeddingInputError):
        asyncio.run(run())


def test_mock_embedding_does_not_access_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Mock Embedding 不应创建网络客户端")

    monkeypatch.setattr(embedding_module.httpx2, "AsyncClient", fail_network)

    service = MockEmbeddingService()

    async def run() -> tuple[list[list[float]], list[float]]:
        return (
            await service.embed_documents(["本地文本"]),
            await service.embed_query("本地查询"),
        )

    documents, query = asyncio.run(run())

    assert len(documents) == 1
    assert len(query) == service.dimension


def test_mock_embedding_works_with_existing_search_service(
    sqlite_session_factory: SessionFactory,
) -> None:
    service = MockEmbeddingService(dimension=32)

    async def seed_and_search() -> list[Any]:
        async with sqlite_session_factory() as session:
            document = Document(
                filename="mock.txt",
                file_type="txt",
                character_count=len("企业知识库检索"),
                status="processed",
            )
            session.add(document)
            await session.flush()
            chunk = DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                text="企业知识库检索",
                character_count=len("企业知识库检索"),
                start_index=0,
                end_index=len("企业知识库检索"),
            )
            session.add(chunk)
            await session.flush()
            vector = (await service.embed_documents([chunk.text]))[0]
            await save_embeddings(
                session,
                [
                    EmbeddingWrite(
                        chunk_id=chunk.id,
                        vector=vector,
                        dimension=service.dimension,
                        model=service.model,
                    )
                ],
            )
            await session.commit()

        async with sqlite_session_factory() as session:
            return await search_chunks(
                session,
                "企业知识库检索",
                embedding_service=service,
            )

    hits = asyncio.run(seed_and_search())

    assert len(hits) == 1
    assert hits[0].text == "企业知识库检索"
    assert hits[0].score == pytest.approx(1.0)


def test_unconfigured_embedding_keeps_original_retrieval_error(
    sqlite_session_factory: SessionFactory,
) -> None:
    async def run() -> None:
        async with sqlite_session_factory() as session:
            await search_chunks(session, "查询", embedding_service=None)

    with pytest.raises(RetrievalError) as exc_info:
        asyncio.run(run())

    assert exc_info.value.code == "embedding_not_configured"
    assert exc_info.value.status_code == 503
