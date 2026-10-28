"""文档向量化编排服务。

编排顺序：
1. 读取文档及其文本块，只保留 ID 和文本的快照；
2. 结束读事务，再调用外部 Embedding，避免数据库事务跨越 HTTP 请求；
3. 校验返回向量数量、维度、数值和顺序；
4. 在单个新事务中批量写入全部向量。

外部服务失败时不会写入任何向量；向量生成与向量存储职责分离。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentEmbeddingError, VectorStoreError
from app.models.document import DocumentChunk
from app.services.document_store import get_document
from app.services.embedding_service import (
    EmbeddingError,
    EmbeddingInputError,
    EmbeddingNotConfiguredError,
    EmbeddingProviderError,
    EmbeddingResponseError,
    EmbeddingService,
    EmbeddingTimeoutError,
)
from app.services.vector_store import (
    MAX_MODEL_NAME_LENGTH,
    EmbeddingWrite,
    save_embeddings,
    validate_vector,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentEmbeddingResult:
    """一次文档向量化的结果。"""

    document_id: int
    chunk_count: int
    embedded_count: int
    dimension: int
    model: str | None
    status: str = "completed"


def _configuration_error() -> DocumentEmbeddingError:
    """构造不泄露密钥的未配置错误。"""
    return DocumentEmbeddingError(
        "Embedding 服务尚未配置，请设置 EMBEDDING_PROVIDER、"
        "EMBEDDING_API_KEY、EMBEDDING_MODEL 和 EMBEDDING_DIMENSION。",
        code="embedding_not_configured",
        status_code=503,
    )


def _map_embedding_error(exc: EmbeddingError) -> DocumentEmbeddingError:
    """把 Embedding 层异常映射为 API 可理解的领域错误。"""
    if isinstance(exc, EmbeddingNotConfiguredError):
        return _configuration_error()
    if isinstance(exc, EmbeddingTimeoutError):
        return DocumentEmbeddingError(
            "Embedding 服务请求超时，未保存任何向量。",
            code="embedding_timeout",
            status_code=504,
        )
    if isinstance(exc, EmbeddingInputError):
        return DocumentEmbeddingError(
            "文本块内容不满足 Embedding 输入要求。",
            code="invalid_embedding_input",
            status_code=422,
        )
    if isinstance(exc, EmbeddingResponseError):
        return DocumentEmbeddingError(
            "Embedding 服务返回的数据格式或维度不合法，未保存任何向量。",
            code="invalid_embedding_response",
            status_code=502,
        )
    if isinstance(exc, EmbeddingProviderError):
        return DocumentEmbeddingError(
            "Embedding 服务调用失败，未保存任何向量，请稍后重试。",
            code="embedding_provider_error",
            status_code=502,
        )
    return DocumentEmbeddingError(
        "Embedding 服务调用失败，未保存任何向量。",
        code="embedding_error",
        status_code=502,
    )


def _normalize_model(service: EmbeddingService) -> str | None:
    """读取模型名，避免把异常类型写入数据库。"""
    model = service.model
    if model is None:
        return None
    if not isinstance(model, str):
        raise DocumentEmbeddingError(
            "Embedding 模型名元数据格式无效。",
            code="invalid_embedding_model",
            status_code=500,
        )
    normalized = model.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_MODEL_NAME_LENGTH:
        raise DocumentEmbeddingError(
            "Embedding 模型名过长，无法写入向量元数据。",
            code="invalid_embedding_model",
            status_code=500,
        )
    return normalized


def _validate_result_vectors(
    vectors: object,
    *,
    expected_count: int,
    dimension: int,
) -> list[list[float]]:
    """校验外部返回值数量和每条向量，再交给仓储二次校验。"""
    if isinstance(vectors, (str, bytes)) or not isinstance(vectors, Sequence):
        raise DocumentEmbeddingError(
            "Embedding 服务返回的向量集合格式不合法。",
            code="invalid_embedding_response",
            status_code=502,
        )

    normalized = list(vectors)
    if len(normalized) != expected_count:
        raise DocumentEmbeddingError(
            "Embedding 返回的向量数量与文本块数量不一致，未保存任何向量。",
            code="invalid_embedding_response",
            status_code=502,
        )

    validated: list[list[float]] = []
    for raw_vector in normalized:
        try:
            validated.append(validate_vector(raw_vector, dimension=dimension))
        except VectorStoreError as exc:
            raise DocumentEmbeddingError(
                "Embedding 返回的向量为空、包含非有限数值或维度不一致。",
                code="invalid_embedding_response",
                status_code=502,
            ) from exc
    return validated


async def embed_document(
    session: AsyncSession,
    document_id: int,
    service: EmbeddingService | None,
) -> DocumentEmbeddingResult:
    """为指定文档的全部文本块生成并保存真实向量。

    Args:
        session: 请求级 AsyncSession；函数内部会结束读事务，再开始保存事务。
        document_id: 已保存文档的主键。
        service: 已配置的 EmbeddingService；None 表示尚未配置。

    Raises:
        DocumentEmbeddingError: 文档无文本块、服务未配置、外部调用失败、
            返回格式异常或向量保存失败。
    """
    try:
        document = await get_document(session, document_id)
        chunks = list(
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
    except Exception:
        # 查询本身失败时释放当前事务；领域异常继续向上传递。
        await session.rollback()
        raise

    # 只保留快照；后面即使 session 回滚，也不需要 ORM 对象保持未过期。
    target_document_id = document.id
    chunk_ids = [chunk.id for chunk in chunks]
    texts = [chunk.text for chunk in chunks]

    # 结束读事务后再调用外部服务，避免长事务占用数据库连接。
    await session.rollback()

    if not chunks:
        raise DocumentEmbeddingError(
            "文档没有可向量化的文本块。",
            code="document_has_no_chunks",
            status_code=422,
        )
    if service is None:
        raise _configuration_error()

    dimension = service.dimension
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        raise DocumentEmbeddingError(
            "Embedding 服务返回的向量维度配置无效。",
            code="invalid_embedding_dimension",
            status_code=500,
        )
    model = _normalize_model(service)

    try:
        raw_vectors = await service.embed_documents(texts)
    except EmbeddingError as exc:
        raise _map_embedding_error(exc) from exc

    vectors = _validate_result_vectors(
        raw_vectors,
        expected_count=len(texts),
        dimension=dimension,
    )

    # save_embeddings 在一个事务中写入全部记录；失败时不保留部分向量。
    items = [
        EmbeddingWrite(
            chunk_id=chunk_id,
            vector=vector,
            dimension=dimension,
            model=model,
        )
        for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
    ]
    saved_count = await save_embeddings(session, items)

    return DocumentEmbeddingResult(
        document_id=target_document_id,
        chunk_count=len(chunks),
        embedded_count=saved_count,
        dimension=dimension,
        model=model,
    )


__all__ = ["DocumentEmbeddingResult", "embed_document"]
