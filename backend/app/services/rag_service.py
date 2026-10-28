"""RAG 问答编排服务。"""

import logging
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentEmbeddingError
from app.models.document import Document
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService, LLMServiceError
from app.services.retrieval import RetrievedChunk, search_chunks

logger = logging.getLogger(__name__)


class RAGError(DocumentEmbeddingError):
    """RAG 编排或答案生成失败。"""


async def _load_filenames(
    session: AsyncSession,
    hits: list[RetrievedChunk],
) -> Mapping[int, str]:
    """批量读取命中文档文件名，不读取向量或其他敏感字段。"""
    document_ids = sorted({hit.document_id for hit in hits})
    if not document_ids:
        return {}

    try:
        result = await session.execute(
            select(Document.id, Document.filename).where(
                Document.id.in_(document_ids)
            )
        )
    except OperationalError as exc:
        await session.rollback()
        logger.error("读取 RAG 来源文件名失败，数据库异常类型=%s", type(exc).__name__)
        raise RAGError(
            "读取问答来源失败，请稍后重试。",
            code="rag_source_unavailable",
            status_code=503,
        ) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error("读取 RAG 来源文件名失败，数据库异常类型=%s", type(exc).__name__)
        raise RAGError(
            "读取问答来源失败，请稍后重试。",
            code="rag_source_error",
            status_code=500,
        ) from None

    return {row.id: row.filename for row in result}


def _build_sources(
    hits: list[RetrievedChunk],
    filenames: Mapping[int, str],
) -> list[ChatSource]:
    """把检索命中映射为不含向量的公开来源。"""
    return [
        ChatSource(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            chunk_index=hit.chunk_index,
            filename=filenames.get(hit.document_id),
            text=hit.text,
            score=hit.score,
        )
        for hit in hits
    ]


async def answer_question(
    session: AsyncSession,
    request: ChatRequest,
    *,
    embedding_service: EmbeddingService | None,
    llm_service: LLMService | None,
) -> ChatResponse:
    """执行检索、答案生成和响应来源组装。"""
    normalized_request = ChatRequest.model_validate(request)
    hits = await search_chunks(
        session,
        normalized_request.question,
        embedding_service=embedding_service,
        top_k=normalized_request.top_k,
        document_id=normalized_request.document_id,
        min_score=normalized_request.min_score,
    )

    if llm_service is None:
        raise RAGError(
            "LLM 服务尚未配置，无法生成回答。",
            code="llm_not_configured",
            status_code=503,
        )

    try:
        answer = await llm_service.generate_answer(
            normalized_request.question,
            [hit.text for hit in hits],
        )
    except LLMServiceError:
        raise RAGError(
            "LLM 服务处理失败，无法生成回答。",
            code="llm_error",
            status_code=502,
        ) from None
    except Exception as exc:
        logger.error("LLM 服务异常类型=%s", type(exc).__name__)
        raise RAGError(
            "LLM 服务处理失败，无法生成回答。",
            code="llm_error",
            status_code=502,
        ) from None

    if not isinstance(answer, str) or not answer.strip():
        raise RAGError(
            "LLM 服务返回了无效回答。",
            code="invalid_llm_response",
            status_code=502,
        )

    filenames = await _load_filenames(session, hits)
    return ChatResponse(
        question=normalized_request.question,
        answer=answer.strip(),
        sources=_build_sources(hits, filenames),
    )


__all__ = ["RAGError", "answer_question"]
