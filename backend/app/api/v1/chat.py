"""RAG 问答 HTTP 接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.documents import get_embedding_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.document import ErrorResponse
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService, LLMServiceError, create_llm_service
from app.services.rag_service import RAGError, answer_question

router = APIRouter(prefix="/chat", tags=["Chat"])


def get_llm_service(
    settings: Settings = Depends(get_settings),
) -> LLMService:
    """按配置返回 Mock 或真实 LLM；测试可通过依赖覆盖替换。"""
    try:
        return create_llm_service(settings)
    except LLMServiceError as exc:
        raise RAGError(
            "LLM 服务尚未配置，无法生成回答。",
            code="llm_not_configured",
            status_code=503,
        ) from None


@router.post(
    "",
    response_model=ChatResponse,
    summary="基于知识库回答问题",
    description=(
        "先检索知识库文本块，再使用可注入的 LLM 服务生成回答。"
        "默认使用不联网的 Mock LLM，不返回原始向量、API Key 或认证信息。"
    ),
    responses={
        422: {"model": ErrorResponse, "description": "问题或检索参数不合法"},
        500: {"model": ErrorResponse, "description": "RAG 内部处理失败"},
        502: {"model": ErrorResponse, "description": "LLM 服务处理失败"},
        503: {"model": ErrorResponse, "description": "Embedding 或 RAG 依赖未配置"},
        504: {"model": ErrorResponse, "description": "依赖服务请求超时"},
    },
)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService | None = Depends(get_embedding_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatResponse:
    """执行一次企业知识库 RAG 问答。"""
    return await answer_question(
        db,
        payload,
        embedding_service=embedding_service,
        llm_service=llm_service,
    )


__all__ = ["get_llm_service", "router"]
