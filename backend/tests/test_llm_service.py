"""LLM 服务抽象和 Mock 实现的公开行为测试。"""

import asyncio
from collections.abc import Sequence

import pytest

from app.services.llm_service import (
    LLMService,
    LLMServiceError,
    MockLLMService,
)


def _generate(
    service: LLMService,
    question: str,
    contexts: Sequence[str],
) -> str:
    return asyncio.run(service.generate_answer(question, contexts))


def test_mock_generates_predictable_answer_from_context() -> None:
    service = MockLLMService()

    answer = _generate(service, "  考勤制度是什么？  ", ["员工应按规定打卡。"])

    assert isinstance(answer, str)
    assert "Mock LLM 回答（仅基于提供的知识库上下文）" in answer
    assert "问题：考勤制度是什么？" in answer
    assert "员工应按规定打卡。" in answer


def test_mock_preserves_order_of_multiple_contexts_and_ignores_blank_items() -> None:
    service = MockLLMService()

    answer = _generate(
        service,
        "请说明流程",
        [" 第一条依据 ", "  ", "第二条依据"],
    )

    assert "[1] 第一条依据" in answer
    assert "[2] 第二条依据" in answer
    assert answer.index("第一条依据") < answer.index("第二条依据")
    assert "[3]" not in answer


def test_mock_returns_explicit_message_without_context() -> None:
    service = MockLLMService()

    assert _generate(service, "没有依据时怎么办？", []) == service.EMPTY_CONTEXT_MESSAGE
    assert _generate(service, "只有空白上下文", [" ", "\n\t"]) == service.EMPTY_CONTEXT_MESSAGE


@pytest.mark.parametrize("question", ["", "   ", "\n\t", None, 123, True])
def test_mock_rejects_empty_or_invalid_question(question: object) -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        _generate(MockLLMService(), question, [])  # type: ignore[arg-type]

    assert exc_info.value.code in {"empty_question", "invalid_question"}
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("contexts", [None, "not-a-sequence", b"bytes", 123, {"x": "y"}])
def test_mock_rejects_invalid_context_container(contexts: object) -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        _generate(MockLLMService(), "问题", contexts)  # type: ignore[arg-type]

    assert exc_info.value.code == "invalid_contexts"


@pytest.mark.parametrize("contexts", [["有效文本", 123], [None], [True]])
def test_mock_rejects_invalid_context_item(contexts: Sequence[object]) -> None:
    with pytest.raises(LLMServiceError) as exc_info:
        _generate(MockLLMService(), "问题", contexts)  # type: ignore[arg-type]

    assert exc_info.value.code == "invalid_context"


def test_mock_is_async_llm_service_implementation() -> None:
    service = MockLLMService()

    assert isinstance(service, LLMService)
    result = asyncio.run(service.generate_answer("问题", ["上下文"]))
    assert isinstance(result, str)


def test_mock_does_not_use_network_clients() -> None:
    service = MockLLMService()

    # Mock 实现没有网络客户端、API Key 或外部调用钩子；调用仅依赖输入。
    assert not hasattr(service, "client")
    assert not hasattr(service, "api_key")
    assert _generate(service, "问题", ["上下文"]) == _generate(
        service,
        "问题",
        ["上下文"],
    )
