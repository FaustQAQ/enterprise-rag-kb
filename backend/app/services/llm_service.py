"""LLM 服务抽象、本地 Mock 与 OpenAI 兼容实现。

本模块只定义问答服务边界和不联网的确定性实现，不依赖任何真实模型 SDK。
未来接入真实 LLM 时，可以实现 ``LLMService.generate_answer``，而无需修改
调用方的输入输出约定。
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

import httpx2

from app.core.config import Settings, get_settings


SUPPORTED_LLM_PROVIDERS = frozenset(
    {"deepseek", "openai_compatible", "openai-compatible"}
)
EMPTY_CONTEXT_MESSAGE = "无法根据提供的知识库上下文回答该问题。"


class LLMServiceError(Exception):
    """LLM 服务输入或处理失败时使用的领域异常。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class LLMService(ABC):
    """统一的异步 LLM 问答服务接口。"""

    @abstractmethod
    async def generate_answer(
        self,
        question: str,
        contexts: Sequence[str],
    ) -> str:
        """根据用户问题和检索上下文生成答案文本。"""


class MockLLMService(LLMService):
    """不联网、可预测且明确标记为 Mock 的问答实现。"""

    EMPTY_CONTEXT_MESSAGE = "Mock LLM 无法根据提供的知识库上下文回答该问题。"

    async def generate_answer(
        self,
        question: str,
        contexts: Sequence[str],
    ) -> str:
        """基于清理后的上下文生成确定性的 Mock 答案。"""
        normalized_question = self._normalize_question(question)
        normalized_contexts = self._normalize_contexts(contexts)

        if not normalized_contexts:
            return self.EMPTY_CONTEXT_MESSAGE

        context_text = "\n\n".join(
            f"[{index}] {context}"
            for index, context in enumerate(normalized_contexts, start=1)
        )
        return (
            "Mock LLM 回答（仅基于提供的知识库上下文）：\n"
            f"问题：{normalized_question}\n"
            f"上下文：\n{context_text}"
        )

    @staticmethod
    def _normalize_question(question: str) -> str:
        """清理问题并拒绝空问题或非字符串输入。"""
        if not isinstance(question, str):
            raise LLMServiceError(
                "问题必须是字符串。",
                code="invalid_question",
            )

        normalized = question.strip()
        if not normalized:
            raise LLMServiceError(
                "问题不能为空。",
                code="empty_question",
            )
        return normalized

    @staticmethod
    def _normalize_contexts(contexts: Sequence[str]) -> list[str]:
        """清理上下文，忽略空白片段并拒绝非法容器或元素。"""
        if isinstance(contexts, (str, bytes)) or not isinstance(contexts, Sequence):
            raise LLMServiceError(
                "contexts 必须是字符串序列。",
                code="invalid_contexts",
            )

        normalized: list[str] = []
        for context in contexts:
            if not isinstance(context, str):
                raise LLMServiceError(
                    "每条上下文必须是字符串。",
                    code="invalid_context",
                )
            stripped = context.strip()
            if stripped:
                normalized.append(stripped)
        return normalized


class OpenAICompatibleLLMService(LLMService):
    """调用 OpenAI Chat Completions 兼容接口的异步 LLM 服务。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise LLMServiceError(
                "LLM API Key 不能为空。",
                code="llm_not_configured",
                status_code=503,
            )
        if not base_url.strip() or not base_url.startswith(("http://", "https://")):
            raise LLMServiceError(
                "LLM Base URL 配置无效。",
                code="llm_not_configured",
                status_code=503,
            )
        if not model.strip():
            raise LLMServiceError(
                "LLM 模型名称不能为空。",
                code="llm_not_configured",
                status_code=503,
            )
        if timeout_seconds <= 0:
            raise LLMServiceError(
                "LLM 超时时间必须大于 0。",
                code="llm_not_configured",
                status_code=503,
            )

        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport

    async def generate_answer(
        self,
        question: str,
        contexts: Sequence[str],
    ) -> str:
        normalized_question = MockLLMService._normalize_question(question)
        normalized_contexts = MockLLMService._normalize_contexts(contexts)

        if not normalized_contexts:
            return EMPTY_CONTEXT_MESSAGE

        context_text = "\n\n".join(
            f"[{index}] {context}"
            for index, context in enumerate(normalized_contexts, start=1)
        )
        system_message = (
            "你是企业知识库问答助手。只能依据用户提供的知识库上下文回答问题。"
            "如果上下文不足以确认答案，必须明确表示无法根据知识库确认，"
            "不得编造事实、来源或上下文之外的信息。"
        )
        user_message = (
            f"问题：{normalized_question}\n\n"
            f"知识库上下文：\n{context_text}"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }

        try:
            async with httpx2.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
        except httpx2.TimeoutException as exc:
            raise LLMServiceError(
                "LLM 服务请求超时，请稍后重试。",
                code="llm_timeout",
                status_code=504,
            ) from exc
        except httpx2.HTTPError as exc:
            raise LLMServiceError(
                "LLM 服务请求失败，请检查网络或服务配置。",
                code="llm_provider_error",
                status_code=502,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise LLMServiceError(
                f"LLM 服务返回 HTTP {response.status_code}。",
                code="llm_provider_error",
                status_code=502,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMServiceError(
                "LLM 服务返回了非 JSON 响应。",
                code="llm_invalid_response",
                status_code=502,
            ) from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMServiceError(
                "LLM 服务返回的数据格式无效。",
                code="llm_invalid_response",
                status_code=502,
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMServiceError(
                "LLM 服务返回了空回答。",
                code="llm_invalid_response",
                status_code=502,
            )
        return content.strip()


def create_llm_service(settings: Settings | None = None) -> LLMService:
    """按配置选择 Mock 或真实 OpenAI 兼容 LLM 服务。"""
    effective = settings or get_settings()

    if effective.llm_mock_enabled:
        if effective.environment == "production":
            raise LLMServiceError(
                "production 环境禁止启用 Mock LLM。",
                code="llm_not_configured",
                status_code=503,
            )
        return MockLLMService()

    provider = (effective.llm_provider or "").strip().lower()
    api_key = (
        effective.llm_api_key.get_secret_value().strip()
        if effective.llm_api_key is not None
        else ""
    )
    base_url = (effective.llm_base_url or "").strip()
    model = (effective.llm_model or "").strip()
    missing: list[str] = []
    if not provider:
        missing.append("LLM_PROVIDER")
    if not api_key:
        missing.append("LLM_API_KEY")
    if not base_url:
        missing.append("LLM_BASE_URL")
    if not model:
        missing.append("LLM_MODEL")
    if missing:
        raise LLMServiceError(
            "LLM 配置不完整，请设置：" + ", ".join(missing) + "。",
            code="llm_not_configured",
            status_code=503,
        )
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise LLMServiceError(
            "不支持的 LLM 提供商配置。",
            code="llm_not_configured",
            status_code=503,
        )

    return OpenAICompatibleLLMService(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=effective.llm_timeout_seconds,
    )


__all__ = [
    "SUPPORTED_LLM_PROVIDERS",
    "LLMService",
    "LLMServiceError",
    "MockLLMService",
    "OpenAICompatibleLLMService",
    "create_llm_service",
]
