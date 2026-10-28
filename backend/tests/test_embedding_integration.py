"""Embedding 服务集成测试。

全部使用 ``httpx2.MockTransport`` 模拟 OpenAI 兼容的 ``/embeddings`` 响应，
不要求真实 API Key，也不会访问网络。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest

from app.core.config import Settings
from app.services.embedding_service import (
    EmbeddingInputError,
    EmbeddingNotConfiguredError,
    EmbeddingProviderError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    OpenAICompatibleEmbeddingService,
    create_embedding_service,
)

SECRET = "test-secret-key"


def _settings(**overrides: Any) -> Settings:
    """构造隔离的配置，避免读取用户本地 .env。"""
    values: dict[str, Any] = {
        "embedding_provider": "openai",
        "embedding_api_key": SECRET,
        "embedding_base_url": "https://embedding.test/v1",
        "embedding_model": "test-embedding",
        "embedding_dimension": 3,
        "embedding_timeout_seconds": 5.0,
        "embedding_batch_size": 2,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _service(
    handler: Any,
    *,
    dimension: int = 3,
    batch_size: int = 2,
) -> OpenAICompatibleEmbeddingService:
    return OpenAICompatibleEmbeddingService(
        api_key=SECRET,
        base_url="https://embedding.test/v1",
        model="test-embedding",
        dimension=dimension,
        timeout_seconds=2.0,
        batch_size=batch_size,
        transport=httpx2.MockTransport(handler),
    )


def test_embed_documents_preserves_order_and_request_contract() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "test-embedding"
        assert payload["input"] == ["第一段", "second"]
        # 故意倒序返回，验证服务按 index 恢复顺序。
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0, 2.0, 2.0]},
                    {"index": 0, "embedding": [1.0, 1.0, 1.0]},
                ]
            },
        )

    service = _service(handler)
    vectors = asyncio.run(service.embed_documents(["第一段", "second"]))

    assert service.dimension == 3
    assert vectors == [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]
    assert len(requests) == 1
    assert str(requests[0].url) == "https://embedding.test/v1/embeddings"
    assert requests[0].headers["authorization"] == f"Bearer {SECRET}"


def test_embed_query_returns_single_vector() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        assert payload["input"] == ["查询文本"]
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    vector = asyncio.run(_service(handler).embed_query("查询文本"))

    assert vector == [0.1, 0.2, 0.3]


def test_embedding_batches_requests_and_keeps_global_order() -> None:
    batches: list[list[str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        batches.append(payload["input"])
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "index": index,
                        "embedding": [float(len(text)), 0.0, 0.0],
                    }
                    for index, text in enumerate(payload["input"])
                ]
            },
        )

    service = _service(handler, batch_size=2)
    vectors = asyncio.run(service.embed_documents(["a", "bb", "ccc"]))

    assert batches == [["a", "bb"], ["ccc"]]
    assert vectors == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]]


def test_empty_document_list_does_not_call_provider() -> None:
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={"data": []})

    assert asyncio.run(_service(handler).embed_documents([])) == []
    assert calls == 0


@pytest.mark.parametrize("texts", [[""], ["   "], ["ok", " \n\t "]])
def test_blank_document_text_is_rejected(texts: list[str]) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("空文本不应调用外部服务")

    with pytest.raises(EmbeddingInputError):
        asyncio.run(_service(handler).embed_documents(texts))


def test_non_string_document_text_is_rejected() -> None:
    with pytest.raises(EmbeddingInputError):
        # 故意传入非法类型，验证运行期输入校验。
        asyncio.run(_service(lambda _request: None).embed_documents(["ok", 1]))  # type: ignore[list-item]


def test_non_sequence_and_blank_query_are_rejected() -> None:
    service = _service(lambda _request: None)

    with pytest.raises(EmbeddingInputError):
        asyncio.run(service.embed_documents("not-a-sequence"))
    with pytest.raises(EmbeddingInputError):
        asyncio.run(service.embed_query(""))
    with pytest.raises(EmbeddingInputError):
        asyncio.run(service.embed_query("   "))


def test_unconfigured_provider_raises_explicit_error() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="EMBEDDING_PROVIDER"):
        create_embedding_service(_settings(embedding_provider=None))


def test_incomplete_configuration_raises_explicit_error() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="EMBEDDING_API_KEY"):
        create_embedding_service(_settings(embedding_api_key=None))


def test_unsupported_provider_raises_explicit_error() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="不支持"):
        create_embedding_service(_settings(embedding_provider="not-supported"))


def test_factory_creates_service_from_settings() -> None:
    service = create_embedding_service(_settings())

    assert isinstance(service, OpenAICompatibleEmbeddingService)
    assert service.dimension == 3


def test_provider_http_error_is_converted_without_leaking_key() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={"error": {"message": "rate limited"}})

    with pytest.raises(EmbeddingProviderError) as exc_info:
        asyncio.run(_service(handler).embed_documents(["hello"]))

    assert exc_info.value.provider_status_code == 429
    assert SECRET not in str(exc_info.value)


def test_provider_network_error_is_converted() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection failed")

    with pytest.raises(EmbeddingProviderError):
        asyncio.run(_service(handler).embed_documents(["hello"]))


def test_provider_timeout_is_converted() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.TimeoutException("timed out")

    with pytest.raises(EmbeddingTimeoutError):
        asyncio.run(_service(handler).embed_documents(["hello"]))


def test_non_json_response_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<html>not json</html>")

    with pytest.raises(EmbeddingResponseError, match="非 JSON"):
        asyncio.run(_service(handler).embed_documents(["hello"]))


def test_vector_count_mismatch_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 2.0, 3.0]}]},
        )

    with pytest.raises(EmbeddingResponseError, match="数量"):
        asyncio.run(_service(handler).embed_documents(["one", "two"]))


def test_vector_dimension_mismatch_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]},
        )

    with pytest.raises(EmbeddingResponseError, match="维度"):
        asyncio.run(_service(handler).embed_documents(["hello"]))


def test_non_numeric_vector_value_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, "oops", 3.0]}]},
        )

    with pytest.raises(EmbeddingResponseError, match="非数值"):
        asyncio.run(_service(handler).embed_documents(["hello"]))


def test_duplicate_vector_index_is_rejected() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 2.0, 3.0]},
                    {"index": 0, "embedding": [4.0, 5.0, 6.0]},
                ]
            },
        )

    with pytest.raises(EmbeddingResponseError, match="重复"):
        asyncio.run(_service(handler).embed_documents(["one", "two"]))
