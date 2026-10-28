"""百炼 text-embedding-v4 兼容协议的离线测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest

from app.services.embedding_service import (
    BAILIAN_TEXT_EMBEDDING_V4_DIMENSIONS,
    EmbeddingNotConfiguredError,
    EmbeddingProviderError,
    EmbeddingResponseError,
    OpenAICompatibleEmbeddingService,
)


SECRET = "fake-bailian-key"


def _service(
    handler: Any,
    *,
    dimension: int = 64,
    batch_size: int = 10,
    base_url: str = "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
) -> OpenAICompatibleEmbeddingService:
    return OpenAICompatibleEmbeddingService(
        api_key=SECRET,
        base_url=base_url,
        model="text-embedding-v4",
        dimension=dimension,
        batch_size=batch_size,
        transport=httpx2.MockTransport(handler),
    )


def test_v4_request_contains_dimensions_and_no_duplicate_embeddings_path() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "text-embedding-v4"
        assert payload["input"] == ["第一段"]
        assert payload["dimensions"] == 64
        assert payload["encoding_format"] == "float"
        return httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0] * 64}]},
        )

    service = _service(
        handler,
        base_url=(
            "https://workspace.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1/embeddings"
        ),
    )
    vectors = asyncio.run(service.embed_documents(["第一段"]))

    assert len(vectors) == 1
    assert str(requests[0].url).endswith(
        "/compatible-mode/v1/embeddings"
    )


@pytest.mark.parametrize("dimension", sorted(BAILIAN_TEXT_EMBEDDING_V4_DIMENSIONS))
def test_v4_accepts_official_dimensions(dimension: int) -> None:
    service = _service(
        lambda _request: httpx2.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0] * dimension}]},
        ),
        dimension=dimension,
    )

    vectors = asyncio.run(service.embed_query("查询"))

    assert len(vectors) == dimension


def test_v4_rejects_unsupported_dimension() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="64、128"):
        _service(lambda _request: httpx2.Response(200), dimension=100)


def test_v4_rejects_batch_size_above_provider_limit() -> None:
    with pytest.raises(EmbeddingNotConfiguredError, match="10"):
        _service(lambda _request: httpx2.Response(200), batch_size=11)


def test_v4_splits_requests_at_ten_items() -> None:
    batches: list[list[str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        batches.append(payload["input"])
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [0.0] * 64}
                    for index in range(len(payload["input"]))
                ]
            },
        )

    service = _service(handler)
    vectors = asyncio.run(
        service.embed_documents([f"text-{index}" for index in range(21)])
    )

    assert [len(batch) for batch in batches] == [10, 10, 1]
    assert len(vectors) == 21
    assert all(len(vector) == 64 for vector in vectors)


def test_other_provider_keeps_existing_batch_behavior_and_optional_dimensions() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert "dimensions" not in payload
        assert "encoding_format" not in payload
        return httpx2.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [1.0, 0.0, 0.0]}
                    for index in range(len(payload["input"]))
                ]
            },
        )

    service = OpenAICompatibleEmbeddingService(
        api_key=SECRET,
        base_url="https://embedding.test/v1",
        model="other-embedding",
        dimension=3,
        batch_size=32,
        transport=httpx2.MockTransport(handler),
    )
    vectors = asyncio.run(service.embed_documents([str(index) for index in range(33)]))

    assert len(vectors) == 33
    assert len(requests) == 2
    assert [len(json.loads(request.content)["input"]) for request in requests] == [32, 1]


def test_v4_rejects_invalid_response_index_count_and_dimension() -> None:
    cases = [
        {"data": [{"index": 0, "embedding": [0.0] * 64}]},
        {
            "data": [
                {"index": 0, "embedding": [0.0] * 64},
                {"index": 0, "embedding": [0.0] * 64},
            ]
        },
        {"data": [{"index": 0, "embedding": [0.0] * 63}]},
    ]

    for body in cases:
        service = _service(lambda _request, body=body: httpx2.Response(200, json=body))
        with pytest.raises(EmbeddingResponseError):
            asyncio.run(service.embed_documents(["one", "two"]))



def test_v4_rejects_non_finite_vector_values() -> None:
    import json

    def handler(_request: httpx2.Request) -> httpx2.Response:
        payload = {
            "data": [
                {
                    "index": 0,
                    "embedding": [float("nan")] + [0.0] * 63,
                }
            ]
        }
        # 模拟供应商返回包含 NaN 的原始 JSON 响应。
        # 必须允许序列化 NaN，不能使用 Response(json=payload)。
        content = json.dumps(payload, allow_nan=True).encode("utf-8")
        return httpx2.Response(
            200,
            content=content,
            headers={"content-type": "application/json"},
        )

    with pytest.raises(EmbeddingResponseError):
        asyncio.run(_service(handler).embed_query("查询"))


def test_provider_error_does_not_leak_api_key() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"error": {"message": f"invalid key {SECRET}"}},
        )

    with pytest.raises(EmbeddingProviderError) as exc_info:
        asyncio.run(_service(handler).embed_query("查询"))

    assert SECRET not in str(exc_info.value)
