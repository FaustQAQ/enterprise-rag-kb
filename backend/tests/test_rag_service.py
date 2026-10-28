"""RAG 编排服务测试。"""

import asyncio
from collections.abc import Sequence

import pytest

from app.schemas.chat import ChatRequest
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.rag_service import RAGError, answer_question
from app.services.retrieval import RetrievedChunk


class FakeLLMService(LLMService):
    """记录输入并返回确定性答案的测试 LLM。"""

    def __init__(self, answer: str = "测试答案", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.questions: list[str] = []
        self.contexts: list[list[str]] = []

    async def generate_answer(self, question: str, contexts: Sequence[str]) -> str:
        self.questions.append(question)
        self.contexts.append(list(contexts))
        if self.error is not None:
            raise self.error
        return self.answer


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


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _answer(
    session_factory: object,
    request: ChatRequest,
    *,
    embedding_service: EmbeddingService | None,
    llm_service: LLMService | None,
) -> object:
    async def run() -> object:
        async with session_factory() as session:  # type: ignore[operator]
            return await answer_question(
                session,
                request,
                embedding_service=embedding_service,
                llm_service=llm_service,
            )

    return run()


def _hits() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(1, 10, 0, "第一条依据", 0.95, "fake-embedding", 4),
        RetrievedChunk(2, 10, 1, "第二条依据", 0.85, "fake-embedding", 4),
    ]


def test_answer_question_passes_hits_to_llm_and_returns_sources(
    sqlite_session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> list[RetrievedChunk]:
        return _hits()

    monkeypatch.setattr("app.services.rag_service.search_chunks", fake_search)
    llm = FakeLLMService()
    request = ChatRequest(question="  企业制度？  ", top_k=2)

    result = _run(
        _answer(
            sqlite_session_factory,
            request,
            embedding_service=FakeEmbeddingService(),
            llm_service=llm,
        )
    )

    assert result.answer == "测试答案"  # type: ignore[union-attr]
    assert [source.text for source in result.sources] == [  # type: ignore[union-attr]
        "第一条依据",
        "第二条依据",
    ]
    assert llm.questions == ["企业制度？"]
    assert llm.contexts == [["第一条依据", "第二条依据"]]


def test_answer_question_calls_llm_with_empty_context_and_empty_sources(
    sqlite_session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> list[RetrievedChunk]:
        return []

    monkeypatch.setattr("app.services.rag_service.search_chunks", fake_search)
    llm = FakeLLMService("Mock LLM 无法根据提供的知识库上下文回答该问题。")

    result = _run(
        _answer(
            sqlite_session_factory,
            ChatRequest(question="未知问题"),
            embedding_service=FakeEmbeddingService(),
            llm_service=llm,
        )
    )

    assert result.sources == []  # type: ignore[union-attr]
    assert "无法根据" in result.answer  # type: ignore[union-attr]
    assert llm.contexts == [[]]


def test_answer_question_maps_llm_failure_without_exposing_details(
    sqlite_session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> list[RetrievedChunk]:
        return []

    monkeypatch.setattr("app.services.rag_service.search_chunks", fake_search)
    secret = "internal provider traceback and api_key=secret"

    with pytest.raises(RAGError) as exc_info:
        _run(
            _answer(
                sqlite_session_factory,
                ChatRequest(question="问题"),
                embedding_service=FakeEmbeddingService(),
                llm_service=FakeLLMService(error=RuntimeError(secret)),
            )
        )

    assert exc_info.value.code == "llm_error"
    assert exc_info.value.status_code == 502
    assert secret not in exc_info.value.message


def test_answer_question_rejects_missing_llm_service(
    sqlite_session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> list[RetrievedChunk]:
        return []

    monkeypatch.setattr("app.services.rag_service.search_chunks", fake_search)

    with pytest.raises(RAGError) as exc_info:
        _run(
            _answer(
                sqlite_session_factory,
                ChatRequest(question="问题"),
                embedding_service=FakeEmbeddingService(),
                llm_service=None,
            )
        )

    assert exc_info.value.code == "llm_not_configured"
