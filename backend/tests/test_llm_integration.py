"""OpenAI 兼容 LLM 服务的离线协议和错误处理测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest

from app.services.llm_service import (
    LLMServiceError,
    OpenAICompatibleLLMService,
)


SECRET = "fake-deepseek-key"


def _service(
    handler: Any,
    *,
    model: str = "deepseek-flash",
) -> OpenAICompatibleLLMService:
    return OpenAICompatibleLLMService(
        api_key=SECRET,
        base_url="https://llm.test",
        model=model,
        timeout_seconds=2.0,
        transport=httpx2.MockTransport(handler),
    )


def test_chat_completion_request_and_answer_parsing() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["stream"] is False
        assert [item["role"] for item in payload["messages"]] == ["system", "user"]
        assert "知识库上下文" in payload["messages"][0]["content"]
        assert "问题：什么是报销制度？" in payload["messages"][1]["content"]
        assert "报销需保留发票" in payload["messages"][1]["content"]
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "  需保留发票。  "}}
                ]
            },
        )

    answer = asyncio.run(
        _service(handler).generate_answer(
            " 什么是报销制度？ ",
            ["报销需保留发票"],
        )
    )

    assert answer == "需保留发票。"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://llm.test/chat/completions"
    assert requests[0].headers["authorization"] == f"Bearer {SECRET}"


def test_empty_context_returns_safe_refusal_without_provider_call() -> None:
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("空上下文不应调用真实 LLM")

    answer = asyncio.run(_service(handler).generate_answer("问题", []))

    assert "无法根据提供的知识库上下文回答" in answer
    assert calls == 0


@pytest.mark.parametrize("status_code", [401, 429, 500])
def test_http_errors_are_sanitized(status_code: int) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code,
            json={"error": {"message": f"provider secret {SECRET}"}},
        )

    with pytest.raises(LLMServiceError) as exc_info:
        asyncio.run(_service(handler).generate_answer("问题", ["上下文"]))

    assert exc_info.value.code == "llm_provider_error"
    assert exc_info.value.status_code == 502
    assert SECRET not in str(exc_info.value)


def test_timeout_is_converted() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.TimeoutException("provider timeout")

    with pytest.raises(LLMServiceError) as exc_info:
        asyncio.run(_service(handler).generate_answer("问题", ["上下文"]))

    assert exc_info.value.code == "llm_timeout"
    assert exc_info.value.status_code == 504
    assert SECRET not in str(exc_info.value)


def test_connection_error_is_converted() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("provider connection failed")

    with pytest.raises(LLMServiceError) as exc_info:
        asyncio.run(_service(handler).generate_answer("问题", ["上下文"]))

    assert exc_info.value.code == "llm_provider_error"
    assert exc_info.value.status_code == 502


def test_non_json_response_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<html>not json</html>")

    with pytest.raises(LLMServiceError) as exc_info:
        asyncio.run(_service(handler).generate_answer("问题", ["上下文"]))

    assert exc_info.value.code == "llm_invalid_response"
    assert exc_info.value.status_code == 502


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
def test_invalid_or_empty_response_is_rejected(body: dict[str, Any]) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=body)

    with pytest.raises(LLMServiceError) as exc_info:
        asyncio.run(_service(handler).generate_answer("问题", ["上下文"]))

    assert exc_info.value.code == "llm_invalid_response"
    assert SECRET not in str(exc_info.value)
