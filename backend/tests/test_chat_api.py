"""RAG 问答 HTTP API 测试。"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.chat import get_llm_service
from app.api.v1.documents import get_embedding_service
from app.main import app
from app.models.document import Document, DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.vector_store import EmbeddingWrite, save_embeddings

SessionFactory = async_sessionmaker[AsyncSession]


class FakeEmbeddingService(EmbeddingService):
    @property
    def dimension(self) -> int:
        return 4

    @property
    def model(self) -> str:
        return "fake-embedding"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class FakeLLMService(LLMService):
    def __init__(self, answer: str = "基于知识库的测试回答") -> None:
        self.answer = answer
        self.contexts: list[list[str]] = []

    async def generate_answer(self, question: str, contexts: Sequence[str]) -> str:
        self.contexts.append(list(contexts))
        return self.answer


def _seed_document(
    session_factory: SessionFactory,
    texts: Sequence[str],
    *,
    filename: str = "问答测试.txt",
    vectors: Sequence[Sequence[float]] | None = None,
) -> int:
    async def run() -> int:
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
                await save_embeddings(
                    session,
                    [
                        EmbeddingWrite(
                            chunk_id=chunk.id,
                            vector=list(vector),
                            dimension=len(vector),
                            model="fake-embedding",
                        )
                        for chunk, vector in zip(chunks, vectors, strict=True)
                    ],
                )
            else:
                await session.commit()
            return document.id

    import asyncio

    return asyncio.run(run())


@contextmanager
def _overrides(
    embedding: EmbeddingService | None,
    llm: LLMService,
) -> Iterator[None]:
    app.dependency_overrides[get_embedding_service] = lambda: embedding
    app.dependency_overrides[get_llm_service] = lambda: llm
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_embedding_service, None)
        app.dependency_overrides.pop(get_llm_service, None)


@contextmanager
def _embedding_only_override(embedding: EmbeddingService) -> Iterator[None]:
    """只替换 Embedding，保留 Chat API 默认的 Mock LLM 依赖。"""
    app.dependency_overrides[get_embedding_service] = lambda: embedding
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_embedding_service, None)


def test_chat_api_returns_answer_sources_and_filename(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    document_id = _seed_document(
        sqlite_session_factory,
        ["第一条知识", "第二条知识"],
        vectors=([1.0, 0.0, 0.0, 0.0], [0.8, 0.6, 0.0, 0.0]),
    )
    llm = FakeLLMService()
    with _overrides(FakeEmbeddingService(), llm):
        response = db_client.post(
            "/api/v1/chat",
            json={"question": "  企业制度？ ", "top_k": 2, "document_id": document_id},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "企业制度？"
    assert body["answer"] == "基于知识库的测试回答"
    assert [source["text"] for source in body["sources"]] == ["第一条知识", "第二条知识"]
    assert all(source["filename"] == "问答测试.txt" for source in body["sources"])
    assert "vector" not in response.text
    assert "api_key" not in response.text.lower()
    assert llm.contexts == [["第一条知识", "第二条知识"]]


def test_chat_api_deduplicates_exact_duplicate_document_sources(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        ["重复来源"],
        filename="相同文档.txt",
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    _seed_document(
        sqlite_session_factory,
        ["重复来源"],
        filename="相同文档.txt",
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    other_id = _seed_document(
        sqlite_session_factory,
        ["重复来源"],
        filename="另一份文档.txt",
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    llm = FakeLLMService()

    with _overrides(FakeEmbeddingService(), llm):
        response = db_client.post(
            "/api/v1/chat",
            json={"question": "问题", "top_k": 10},
        )

    assert response.status_code == 200
    sources = response.json()["sources"]
    assert len(sources) == 2
    assert {source["filename"] for source in sources} == {"相同文档.txt", "另一份文档.txt"}
    assert other_id in {source["document_id"] for source in sources}
    assert llm.contexts == [["重复来源", "重复来源"]]


def test_chat_api_without_matching_results_returns_empty_sources(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(sqlite_session_factory, ["没有向量的文本"], vectors=None)
    with _overrides(FakeEmbeddingService(), FakeLLMService("无法根据知识库回答")):
        response = db_client.post("/api/v1/chat", json={"question": "问题"})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "无法根据知识库回答" in response.json()["answer"]


def test_chat_api_default_mock_llm_refuses_without_context(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(sqlite_session_factory, ["没有对应向量的文本"], vectors=None)

    with _embedding_only_override(FakeEmbeddingService()):
        response = db_client.post("/api/v1/chat", json={"question": "未知问题"})

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert "无法根据提供的知识库上下文回答" in body["answer"]
    assert "vector" not in response.text
    assert "api_key" not in response.text.lower()


@pytest.mark.parametrize(
    ("min_score", "expected_source_count"),
    [
        (0.7, 1),
        (0.8, 1),
        (0.81, 0),
    ],
)
def test_chat_api_min_score_controls_sources_and_default_refusal(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
    min_score: float,
    expected_source_count: int,
) -> None:
    document_id = _seed_document(
        sqlite_session_factory,
        ["阈值测试文本"],
        vectors=([0.8, 0.6, 0.0, 0.0],),
    )

    with _embedding_only_override(FakeEmbeddingService()):
        response = db_client.post(
            "/api/v1/chat",
            json={
                "question": "阈值查询",
                "document_id": document_id,
                "min_score": min_score,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["sources"]) == expected_source_count
    if expected_source_count == 0:
        assert "无法根据提供的知识库上下文回答" in body["answer"]
    else:
        assert body["sources"][0]["text"] == "阈值测试文本"


def test_chat_api_maps_embedding_not_configured(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(sqlite_session_factory, ["文本"], vectors=None)
    with _overrides(None, FakeLLMService()):
        response = db_client.post("/api/v1/chat", json={"question": "问题"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "embedding_not_configured"
    assert "api_key" not in response.text.lower()


@pytest.mark.parametrize("payload", [{"question": ""}, {"question": " "}, {"question": "问题", "top_k": 0}, {"question": "问题", "top_k": 21}, {"question": "问题", "top_k": True}, {"question": "问题", "min_score": 1.01}, {"question": "问题", "min_score": True}])
def test_chat_api_rejects_invalid_request(
    db_client: TestClient,
    payload: dict[str, Any],
) -> None:
    response = db_client.post("/api/v1/chat", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_chat_api_maps_llm_failure_without_internal_details(
    db_client: TestClient,
    sqlite_session_factory: SessionFactory,
) -> None:
    _seed_document(
        sqlite_session_factory,
        ["文本"],
        vectors=([1.0, 0.0, 0.0, 0.0],),
    )
    class FailingLLM(LLMService):
        async def generate_answer(self, question: str, contexts: Sequence[str]) -> str:
            raise RuntimeError("secret traceback api_key=do-not-return")

    with _overrides(FakeEmbeddingService(), FailingLLM()):
        response = db_client.post("/api/v1/chat", json={"question": "问题"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_error"
    assert "secret traceback" not in response.text
    assert "api_key" not in response.text.lower()


def test_chat_api_openapi_contains_route(db_client: TestClient) -> None:
    paths = db_client.get("/openapi.json").json()["paths"]
    assert "/api/v1/chat" in paths
    assert "post" in paths["/api/v1/chat"]
