"""检索 HTTP 接口。

路由层只负责请求校验和响应封装；文本向量化、相似度计算和数据库读取均复用
``app.services.retrieval``。Embedding 依赖复用文档接口中已有的
``get_embedding_service``，未配置时返回 503，不生成替代向量。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.documents import get_embedding_service
from app.core.database import get_db
from app.schemas.document import ErrorResponse
from app.schemas.retrieval import (
    RetrievalHit,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from app.services.embedding_service import EmbeddingService
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


@router.post(
    "/search",
    response_model=RetrievalSearchResponse,
    summary="检索相似文本块",
    description=(
        "把查询文本转换为向量，在已保存的文本块向量中按余弦相似度检索。"
        "只返回兼容维度和模型的向量；响应不包含原始向量、API Key 或认证信息。"
        "Embedding 未配置时返回统一格式的 503 错误。"
    ),
    responses={
        422: {"model": ErrorResponse, "description": "查询文本或参数不合法"},
        500: {"model": ErrorResponse, "description": "检索或内部处理失败"},
        502: {"model": ErrorResponse, "description": "Embedding 服务调用或响应异常"},
        503: {"model": ErrorResponse, "description": "Embedding 未配置或数据库暂时不可用"},
        504: {"model": ErrorResponse, "description": "Embedding 服务请求超时"},
    },
)
async def search_text_chunks(
    payload: RetrievalSearchRequest,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService | None = Depends(get_embedding_service),
) -> RetrievalSearchResponse:
    """执行一次文本块相似度检索。"""
    hits = await search_chunks(
        db,
        payload.query,
        embedding_service=embedding_service,
        top_k=payload.top_k,
        document_id=payload.document_id,
        min_score=payload.min_score,
    )

    return RetrievalSearchResponse(
        query=payload.query.strip(),
        hits=[RetrievalHit.model_validate(hit) for hit in hits],
    )


__all__ = ["router"]
