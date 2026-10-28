"""Embedding 服务接口、具体实现与配置工厂。

本模块只负责“文本 -> 向量”的调用编排，不负责文本切分、数据库持久化或向量
检索。当前提供一个 OpenAI 兼容的 HTTP 适配器，以及仅在显式开启时使用的本地
确定性 Mock；关闭 Mock 且没有配置真实提供商时，``create_embedding_service``
会抛出 ``EmbeddingNotConfiguredError``。Mock 结果不代表真实语义 Embedding。

接口约定：
- ``embed_documents`` 的输出数量、顺序必须与输入文本完全一致。
- ``embed_query`` 与 ``embed_documents`` 必须使用同一个向量空间和维度。
- 空文本列表返回空列表，不调用外部服务；列表中的空字符串或非字符串会抛出
  ``EmbeddingInputError``。
- 外部服务失败、超时、返回格式异常分别映射为明确的 Embedding 异常，错误信息
  不包含 API Key 或完整请求正文。
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

import httpx2

from app.core.config import Settings, get_settings

# 当前只实现一种 HTTP 协议；显式列出别名，未知值在工厂层报配置错误。
SUPPORTED_EMBEDDING_PROVIDERS = frozenset(
    {"openai", "openai_compatible", "openai-compatible"}
)
BAILIAN_TEXT_EMBEDDING_V4_MODEL = "text-embedding-v4"
BAILIAN_TEXT_EMBEDDING_V4_DIMENSIONS = frozenset(
    {64, 128, 256, 512, 768, 1024, 1536, 2048}
)
BAILIAN_TEXT_EMBEDDING_V4_MAX_BATCH_SIZE = 10


class EmbeddingError(Exception):
    """Embedding 服务相关错误的基类。"""

    code = "embedding_error"


class EmbeddingNotConfiguredError(EmbeddingError):
    """尚未配置真实 Embedding 提供商，或配置不完整。"""

    code = "embedding_not_configured"


class EmbeddingInputError(EmbeddingError, ValueError):
    """输入文本为空、类型错误或不符合接口约定。"""

    code = "invalid_embedding_input"


class EmbeddingProviderError(EmbeddingError):
    """外部 Embedding 服务不可用、返回非成功状态或网络请求失败。"""

    code = "embedding_provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status_code = provider_status_code


class EmbeddingTimeoutError(EmbeddingProviderError):
    """外部 Embedding 服务请求超时。"""

    code = "embedding_timeout"


class EmbeddingResponseError(EmbeddingError):
    """外部服务响应不是预期的 JSON、数量或向量格式。"""

    code = "invalid_embedding_response"


class EmbeddingService(ABC):
    """Embedding 服务抽象基类。

    具体实现可以是在线 API、私有化模型或本地推理服务。业务代码只依赖本接口，
    不直接依赖某个供应商的 SDK，便于后续替换模型或接入向量存储。
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度，供建表和相似度校验使用。"""

    @property
    def model(self) -> str | None:
        """返回真实模型名称；未知时允许为 None，供持久化元数据记录。"""
        return None

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """批量把文档文本转换为向量，保持输入顺序和数量。"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """把单条查询文本转换为向量。"""


class MockEmbeddingService(EmbeddingService):
    """使用稳定特征哈希生成本地测试向量的 Embedding 实现。

    该实现不是语义模型，只用于本地开发和自动化测试。查询和文档向量共享
    同一套特征提取与哈希规则，因此可以直接复用现有的向量存储和检索流程。
    """

    DEFAULT_DIMENSION = 64
    MODEL_NAME = "local-mock-embedding-v1"

    def __init__(
        self,
        *,
        dimension: int = DEFAULT_DIMENSION,
        model: str = MODEL_NAME,
    ) -> None:
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise EmbeddingNotConfiguredError("Mock Embedding 维度必须是正整数。")
        if not isinstance(model, str) or not model.strip():
            raise EmbeddingNotConfiguredError("Mock Embedding 模型标识不能为空。")
        self._dimension = dimension
        self._model = model.strip()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = self._validate_texts(texts)
        return [self._embed_text(text) for text in normalized]

    async def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise EmbeddingInputError("查询文本必须是字符串。")
        if not text.strip():
            raise EmbeddingInputError("查询文本不能为空或只包含空白字符。")
        return self._embed_text(text)

    def _validate_texts(self, texts: Sequence[str]) -> list[str]:
        if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
            raise EmbeddingInputError("texts 必须是字符串序列。")

        normalized = list(texts)
        for position, text in enumerate(normalized, start=1):
            if not isinstance(text, str):
                raise EmbeddingInputError(f"第 {position} 个文本必须是字符串。")
            if not text.strip():
                raise EmbeddingInputError(
                    f"第 {position} 个文本不能为空或只包含空白字符。"
                )
        return normalized

    def _embed_text(self, text: str) -> list[float]:
        features = re.findall(r"\w+|[^\w\s]", text.casefold(), flags=re.UNICODE)
        if not features:
            features = [text.strip().casefold()]

        vector = [0.0] * self._dimension
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            raise EmbeddingResponseError("Mock Embedding 无法生成有效向量。")
        return [value / norm for value in vector]


class OpenAICompatibleEmbeddingService(EmbeddingService):
    """调用 OpenAI 兼容 ``/embeddings`` 接口的 Embedding 服务。

    请求格式::

        POST {base_url}/embeddings
        Authorization: Bearer <EMBEDDING_API_KEY>
        {"model": "<EMBEDDING_MODEL>", "input": ["文本 1", "文本 2"]}

    响应中的 ``data[].index`` 用于恢复顺序，``data[].embedding`` 必须是长度等于
    配置维度的有限数值数组。网络客户端可以注入 ``transport``，测试时使用
    ``httpx2.MockTransport``，不需要真实网络或 API Key。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int,
        timeout_seconds: float = 30.0,
        batch_size: int = 32,
        dimensions: int | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise EmbeddingNotConfiguredError("Embedding API Key 不能为空。")
        if not base_url.strip():
            raise EmbeddingNotConfiguredError("Embedding Base URL 不能为空。")
        if not base_url.startswith(("http://", "https://")):
            raise EmbeddingNotConfiguredError(
                "Embedding Base URL 必须使用 http:// 或 https://。"
            )
        if not model.strip():
            raise EmbeddingNotConfiguredError("Embedding 模型名称不能为空。")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise EmbeddingNotConfiguredError("Embedding 维度必须是正整数。")
        if timeout_seconds <= 0:
            raise EmbeddingNotConfiguredError("Embedding 超时时间必须大于 0。")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise EmbeddingNotConfiguredError("Embedding 批大小必须是正整数。")
        if dimensions is not None and (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or dimensions <= 0
        ):
            raise EmbeddingNotConfiguredError("Embedding 请求维度必须是正整数。")
        normalized_model = model.strip()
        request_dimensions = dimensions
        if normalized_model == BAILIAN_TEXT_EMBEDDING_V4_MODEL:
            request_dimensions = request_dimensions or dimension
            if request_dimensions not in BAILIAN_TEXT_EMBEDDING_V4_DIMENSIONS:
                raise EmbeddingNotConfiguredError(
                    "text-embedding-v4 的向量维度必须是 64、128、256、512、"
                    "768、1024、1536 或 2048。"
                )
            if request_dimensions != dimension:
                raise EmbeddingNotConfiguredError(
                    "Embedding 请求维度必须与本地校验维度一致。"
                )
            if batch_size > BAILIAN_TEXT_EMBEDDING_V4_MAX_BATCH_SIZE:
                raise EmbeddingNotConfiguredError(
                    "text-embedding-v4 单次请求最多包含 10 条文本。"
                )

        self._api_key = api_key.strip()
        normalized_base_url = base_url.rstrip("/")
        if normalized_base_url.endswith("/embeddings"):
            normalized_base_url = normalized_base_url[: -len("/embeddings")].rstrip("/")
        self._base_url = normalized_base_url
        self._model = normalized_model
        self._dimension = dimension
        self._timeout_seconds = float(timeout_seconds)
        self._batch_size = batch_size
        self._dimensions = request_dimensions
        self._transport = transport

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str | None:
        """返回配置的真实模型名，写入向量元数据。"""
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """批量向量化；空列表直接返回空列表，不创建 HTTP 请求。"""
        normalized = self._validate_texts(texts)
        if not normalized:
            return []
        return await self._embed_texts(normalized)

    async def embed_query(self, text: str) -> list[float]:
        """向量化单条查询文本。"""
        if not isinstance(text, str):
            raise EmbeddingInputError("查询文本必须是字符串。")
        if not text.strip():
            raise EmbeddingInputError("查询文本不能为空或只包含空白字符。")
        vectors = await self._embed_texts([text])
        return vectors[0]

    def _validate_texts(self, texts: Sequence[str]) -> list[str]:
        """校验批量输入；空字符串和非字符串不会发送到外部服务。"""
        if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
            raise EmbeddingInputError("texts 必须是字符串序列。")

        normalized = list(texts)
        for position, text in enumerate(normalized, start=1):
            if not isinstance(text, str):
                raise EmbeddingInputError(
                    f"第 {position} 个文本必须是字符串。"
                )
            if not text.strip():
                raise EmbeddingInputError(
                    f"第 {position} 个文本不能为空或只包含空白字符。"
                )
        return normalized

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """按批大小调用外部服务，并按批次顺序拼接结果。"""
        vectors: list[list[float]] = []
        async with httpx2.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                vectors.extend(await self._request_batch(client, batch))
        return vectors

    async def _request_batch(
        self,
        client: httpx2.AsyncClient,
        texts: list[str],
    ) -> list[list[float]]:
        """请求单批文本，并把网络/HTTP/解析异常转换为领域异常。"""
        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        if self._dimensions is not None:
            payload["dimensions"] = self._dimensions
            payload["encoding_format"] = "float"

        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx2.TimeoutException as exc:
            raise EmbeddingTimeoutError(
                "Embedding 服务请求超时，请稍后重试。"
            ) from exc
        except httpx2.HTTPError as exc:
            raise EmbeddingProviderError(
                "Embedding 服务请求失败，请检查网络或服务配置。"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise EmbeddingProviderError(
                f"Embedding 服务返回 HTTP {response.status_code}。",
                provider_status_code=response.status_code,
            )

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise EmbeddingResponseError(
                "Embedding 服务返回了非 JSON 响应。"
            ) from exc

        return self._parse_response(body, expected_count=len(texts))

    def _parse_response(
        self,
        body: Any,
        *,
        expected_count: int,
    ) -> list[list[float]]:
        """校验响应结构、索引、数量和每条向量的维度/数值。"""
        if not isinstance(body, dict):
            raise EmbeddingResponseError("Embedding 响应必须是 JSON 对象。")

        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingResponseError(
                "Embedding 响应中的向量数量与输入文本数量不一致。"
            )

        indexed_vectors: list[tuple[int, list[float]]] = []
        seen_indexes: set[int] = set()
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingResponseError("Embedding 响应中的 data 项必须是对象。")

            raw_index = item.get("index", position)
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise EmbeddingResponseError("Embedding 响应的 index 必须是整数。")
            if raw_index < 0 or raw_index >= expected_count:
                raise EmbeddingResponseError("Embedding 响应的 index 超出有效范围。")
            if raw_index in seen_indexes:
                raise EmbeddingResponseError("Embedding 响应的 index 存在重复。")
            seen_indexes.add(raw_index)

            vector = self._normalize_vector(item.get("embedding"), raw_index)
            indexed_vectors.append((raw_index, vector))

        indexed_vectors.sort(key=lambda item: item[0])
        if [index for index, _ in indexed_vectors] != list(range(expected_count)):
            raise EmbeddingResponseError("Embedding 响应的 index 不完整。")

        return [vector for _, vector in indexed_vectors]

    def _normalize_vector(self, raw_vector: Any, index: int) -> list[float]:
        """把一条供应商向量转换为有限浮点数数组，并校验维度。"""
        if isinstance(raw_vector, (str, bytes)) or not isinstance(
            raw_vector, Sequence
        ):
            raise EmbeddingResponseError(
                f"Embedding 响应中第 {index} 条向量不是数组。"
            )
        if len(raw_vector) != self._dimension:
            raise EmbeddingResponseError(
                "Embedding 响应中的向量维度与配置不一致："
                f"期望 {self._dimension}，实际 {len(raw_vector)}。"
            )

        vector: list[float] = []
        for value in raw_vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingResponseError(
                    f"Embedding 响应中第 {index} 条向量包含非数值。"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EmbeddingResponseError(
                    f"Embedding 响应中第 {index} 条向量包含 NaN 或无穷大。"
                )
            vector.append(number)
        return vector


def create_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    """根据配置创建 Embedding 服务。

    未配置提供商或配置不完整时抛出 ``EmbeddingNotConfiguredError``；只有显式
    配置了 provider、API Key、模型和维度后才会创建真实 HTTP 适配器。该函数
    不发起网络请求，调用方可以在应用启动或依赖注入阶段安全地使用。
    """
    effective = settings or get_settings()

    if effective.embedding_mock_enabled:
        if effective.environment == "production":
            raise EmbeddingNotConfiguredError(
                "production 环境禁止启用 Mock Embedding。"
            )
        return MockEmbeddingService(
            dimension=(
                effective.embedding_dimension
                or MockEmbeddingService.DEFAULT_DIMENSION
            )
        )

    provider = (effective.embedding_provider or "").strip().lower()

    if not provider:
        raise EmbeddingNotConfiguredError(
            "未配置 Embedding 提供商，请设置 EMBEDDING_PROVIDER。"
        )
    if provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise EmbeddingNotConfiguredError(
            f"不支持的 Embedding 提供商：{provider}。"
        )

    api_key = (
        effective.embedding_api_key.get_secret_value().strip()
        if effective.embedding_api_key is not None
        else ""
    )
    base_url = (effective.embedding_base_url or "").strip()
    model = (effective.embedding_model or "").strip()
    dimension = effective.embedding_dimension

    missing: list[str] = []
    if not api_key:
        missing.append("EMBEDDING_API_KEY")
    if not base_url:
        missing.append("EMBEDDING_BASE_URL")
    if not model:
        missing.append("EMBEDDING_MODEL")
    if dimension is None:
        missing.append("EMBEDDING_DIMENSION")
    if missing:
        raise EmbeddingNotConfiguredError(
            "Embedding 配置不完整，请设置：" + ", ".join(missing) + "。"
        )

    return OpenAICompatibleEmbeddingService(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dimension=dimension,
        timeout_seconds=effective.embedding_timeout_seconds,
        batch_size=effective.embedding_batch_size,
    )


__all__ = [
    "SUPPORTED_EMBEDDING_PROVIDERS",
    "BAILIAN_TEXT_EMBEDDING_V4_MODEL",
    "BAILIAN_TEXT_EMBEDDING_V4_DIMENSIONS",
    "BAILIAN_TEXT_EMBEDDING_V4_MAX_BATCH_SIZE",
    "EmbeddingError",
    "EmbeddingInputError",
    "EmbeddingNotConfiguredError",
    "EmbeddingProviderError",
    "EmbeddingResponseError",
    "EmbeddingService",
    "EmbeddingTimeoutError",
    "MockEmbeddingService",
    "OpenAICompatibleEmbeddingService",
    "create_embedding_service",
]
