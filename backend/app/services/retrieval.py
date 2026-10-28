"""文本块向量检索服务。

本模块只负责“查询向量 / 查询文本 -> 相似文本块”的计算，不新增 HTTP API，
也不修改数据库模型。向量仍然以 JSON 数组保存在 SQLite 中，因此检索在 Python
侧完成余弦相似度计算，适合当前单机开发阶段；后续切换 pgvector 时可以保留
``search_similar_chunks`` / ``search_chunks`` 的输入输出契约。

模型隔离策略：
- 显式传入 ``model`` 时，只比较该模型生成的向量。
- ``model`` 为 ``None`` 时，只比较 ``model`` 字段为 NULL 的向量，避免把不同
  来源的向量静默混合。调用方若知道当前查询模型，应显式传入。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentEmbeddingError, VectorStoreError
from app.models.document import Document, DocumentChunk, DocumentChunkEmbedding
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
    MAX_VECTOR_DIMENSION,
    validate_vector,
)

logger = logging.getLogger(__name__)

MAX_TOP_K = 100


class RetrievalError(DocumentEmbeddingError):
    """检索参数、数据库访问或查询向量不合法。"""


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """一条检索命中结果；不包含原始向量。"""

    chunk_id: int
    document_id: int
    chunk_index: int
    text: str
    score: float
    model: str | None
    dimension: int


def _validated_query_vector(raw_vector: object, *, field: str) -> list[float]:
    """校验单条查询向量，复用仓储层的有限数值/维度校验。

    ``validate_vector`` 需要一个期望维度；这里先用数组自身长度作为期望维度，
    因此空数组、字符串、非序列等输入仍会被仓储层或前置类型检查拒绝。
    """
    if isinstance(raw_vector, (str, bytes)) or not isinstance(
        raw_vector, Sequence
    ):
        raise VectorStoreError(
            f"{field}必须是数值数组。",
            code="invalid_vector",
            status_code=422,
        )
    if len(raw_vector) == 0:
        raise VectorStoreError(
            f"{field}不能为空。",
            code="invalid_vector",
            status_code=422,
        )
    return validate_vector(raw_vector, dimension=len(raw_vector))


def _cosine_similarity_validated(
    query_vector: Sequence[float],
    chunk_vector: Sequence[float],
) -> float:
    """计算两个已校验向量的余弦相似度。

    零向量没有方向，统一返回 0.0，避免除以零；不会静默伪造非零相似度。
    """
    dot_product = math.fsum(
        query_value * chunk_value
        for query_value, chunk_value in zip(query_vector, chunk_vector, strict=True)
    )
    query_norm = math.sqrt(math.fsum(value * value for value in query_vector))
    chunk_norm = math.sqrt(math.fsum(value * value for value in chunk_vector))

    if query_norm == 0.0 or chunk_norm == 0.0:
        return 0.0

    score = dot_product / (query_norm * chunk_norm)
    # 浮点误差可能让结果略超出 [-1, 1]，截断到余弦相似度的合法范围。
    return max(-1.0, min(1.0, score))


def cosine_similarity(
    query_vector: Sequence[float],
    chunk_vector: Sequence[float],
) -> float:
    """计算查询向量与文本块向量的余弦相似度。

    输入必须是等长的有限数值数组。空数组、字符串、非数值、NaN/Infinity 和
    维度不一致都会抛出 ``VectorStoreError``；零向量返回 0.0。
    """
    normalized_query = _validated_query_vector(query_vector, field="查询向量")
    normalized_chunk = _validated_query_vector(chunk_vector, field="文本块向量")

    if len(normalized_query) != len(normalized_chunk):
        raise VectorStoreError(
            "查询向量与文本块向量维度不一致："
            f"{len(normalized_query)} != {len(normalized_chunk)}。",
            code="invalid_vector_dimension",
            status_code=422,
        )

    return _cosine_similarity_validated(normalized_query, normalized_chunk)


def _validate_top_k(top_k: object) -> int:
    """限制单次检索返回数量，避免一次加载过多结果。"""
    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k < 1
        or top_k > MAX_TOP_K
    ):
        raise RetrievalError(
            f"top_k 必须是 1 到 {MAX_TOP_K} 之间的整数。",
            code="invalid_top_k",
            status_code=422,
        )
    return top_k


def _validate_min_score(min_score: object) -> float | None:
    """过滤阈值必须是与余弦相似度同量纲的有限数值。"""
    if min_score is None:
        return None
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)):
        raise RetrievalError(
            "min_score 必须是 -1 到 1 之间的数值。",
            code="invalid_min_score",
            status_code=422,
        )
    value = float(min_score)
    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise RetrievalError(
            "min_score 必须是 -1 到 1 之间的有限数值。",
            code="invalid_min_score",
            status_code=422,
        )
    return value


def _validate_document_id(document_id: object) -> int | None:
    """文档筛选条件必须为正整数或 None。"""
    if document_id is None:
        return None
    if (
        isinstance(document_id, bool)
        or not isinstance(document_id, int)
        or document_id <= 0
    ):
        raise RetrievalError(
            "document_id 必须是正整数或空值。",
            code="invalid_document_id",
            status_code=422,
        )
    return document_id


def _normalize_model(model: object) -> str | None:
    """清洗模型名；None 有明确的“仅比较无模型元数据向量”语义。"""
    if model is None:
        return None
    if not isinstance(model, str):
        raise RetrievalError(
            "model 必须是字符串或空值。",
            code="invalid_model",
            status_code=422,
        )
    normalized = model.strip()
    if not normalized:
        raise RetrievalError(
            "model 不能为空字符串。",
            code="invalid_model",
            status_code=422,
        )
    if len(normalized) > MAX_MODEL_NAME_LENGTH:
        raise RetrievalError(
            f"model 不能超过 {MAX_MODEL_NAME_LENGTH} 个字符。",
            code="invalid_model",
            status_code=422,
        )
    return normalized


def _normalize_query(query: object) -> str:
    """校验查询文本，返回去除首尾空白后的文本。"""
    if not isinstance(query, str):
        raise RetrievalError(
            "查询文本必须是字符串。",
            code="invalid_query",
            status_code=422,
        )
    normalized = query.strip()
    if not normalized:
        raise RetrievalError(
            "查询文本不能为空或只包含空白字符。",
            code="empty_query",
            status_code=422,
        )
    return normalized


def _map_embedding_error(exc: EmbeddingError) -> RetrievalError:
    """把 Embedding 层异常转换为检索层可读错误。"""
    if isinstance(exc, EmbeddingNotConfiguredError):
        return RetrievalError(
            "Embedding 服务尚未配置，无法生成查询向量。",
            code="embedding_not_configured",
            status_code=503,
        )
    if isinstance(exc, EmbeddingTimeoutError):
        return RetrievalError(
            "Embedding 服务请求超时，无法完成检索。",
            code="embedding_timeout",
            status_code=504,
        )
    if isinstance(exc, EmbeddingInputError):
        return RetrievalError(
            "查询文本不满足 Embedding 输入要求。",
            code="invalid_embedding_input",
            status_code=422,
        )
    if isinstance(exc, EmbeddingResponseError):
        return RetrievalError(
            "Embedding 服务返回的查询向量格式不合法。",
            code="invalid_embedding_response",
            status_code=502,
        )
    if isinstance(exc, EmbeddingProviderError):
        return RetrievalError(
            "Embedding 服务调用失败，无法完成检索。",
            code="embedding_provider_error",
            status_code=502,
        )
    return RetrievalError(
        "Embedding 服务调用失败，无法完成检索。",
        code="embedding_error",
        status_code=502,
    )


def _database_error(
    *,
    operation: str,
    exc: Exception,
    code: str,
    status_code: int,
    message: str,
) -> RetrievalError:
    """只记录异常类型，不记录 SQL 参数、正文或向量。"""
    logger.error("%s失败，数据库异常类型=%s", operation, type(exc).__name__)
    return RetrievalError(message, code=code, status_code=status_code)


async def search_similar_chunks(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    top_k: int = 5,
    document_id: int | None = None,
    model: str | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """按余弦相似度检索文本块。

    Args:
        session: 请求级 AsyncSession，只执行只读查询。
        query_vector: 查询向量；必须与库中向量维度一致。
        top_k: 最多返回条数，范围 1..100。
        document_id: 可选文档范围；不会跨文档误召回。
        model: 可选模型名；None 时只比较 model 为 NULL 的向量。
        min_score: 可选最低余弦相似度，范围 [-1, 1]。

    结果按 ``score`` 降序排列；同分时按 ``document_id``、``chunk_index``、
    ``chunk_id`` 升序排列，保证输出稳定。返回项不包含原始向量。
    """
    normalized_query = _validated_query_vector(query_vector, field="查询向量")
    dimension = len(normalized_query)
    safe_top_k = _validate_top_k(top_k)
    safe_document_id = _validate_document_id(document_id)
    safe_model = _normalize_model(model)
    safe_min_score = _validate_min_score(min_score)

    statement = (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.text,
            Document.filename,
            DocumentChunkEmbedding.vector,
            DocumentChunkEmbedding.dimension,
            DocumentChunkEmbedding.model,
        )
        .join(
            DocumentChunkEmbedding,
            DocumentChunkEmbedding.chunk_id == DocumentChunk.id,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunkEmbedding.dimension == dimension)
    )
    if safe_document_id is not None:
        statement = statement.where(
            DocumentChunk.document_id == safe_document_id
        )
    if safe_model is None:
        # 没有模型信息时只比较同样没有模型信息的向量，避免混合不同向量空间。
        statement = statement.where(DocumentChunkEmbedding.model.is_(None))
    else:
        statement = statement.where(DocumentChunkEmbedding.model == safe_model)

    try:
        rows = (await session.execute(statement)).all()
    except OperationalError as exc:
        await session.rollback()
        raise _database_error(
            operation="检索文本块",
            exc=exc,
            code="database_unavailable",
            status_code=503,
            message="数据库暂时不可用，请稍后重试。",
        ) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _database_error(
            operation="检索文本块",
            exc=exc,
            code="database_error",
            status_code=500,
            message="检索失败，请稍后重试。",
        ) from None

    hits: list[RetrievedChunk] = []
    exact_duplicate_keys: set[tuple[str, int, str, str | None, int]] = set()
    for row in rows:
        try:
            stored_vector = validate_vector(row.vector, dimension=dimension)
        except VectorStoreError as exc:
            # 库内数据损坏属于服务端错误，不伪装成 422 客户端错误。
            raise RetrievalError(
                "已存储的向量格式无效，无法执行检索。",
                code="invalid_stored_vector",
                status_code=500,
            ) from exc

        score = _cosine_similarity_validated(normalized_query, stored_vector)
        if safe_min_score is not None and score < safe_min_score:
            continue
        duplicate_key = (
            row.filename,
            row.chunk_index,
            row.text,
            row.model,
            row.dimension,
        )
        if duplicate_key in exact_duplicate_keys:
            continue
        exact_duplicate_keys.add(duplicate_key)
        hits.append(
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                text=row.text,
                score=score,
                model=row.model,
                dimension=row.dimension,
            )
        )

    hits.sort(
        key=lambda hit: (
            -hit.score,
            hit.document_id,
            hit.chunk_index,
            hit.chunk_id,
        )
    )
    return hits[:safe_top_k]


async def search_chunks(
    session: AsyncSession,
    query: str,
    *,
    embedding_service: EmbeddingService | None,
    top_k: int = 5,
    document_id: int | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """把查询文本向量化后执行文本块检索。

    查询文本会先去除首尾空白；空文本、未配置 Embedding、供应商失败、返回向量
    格式或维度异常都会转换为 ``RetrievalError``。模型名和维度取自
    ``embedding_service``，并作为检索过滤条件，避免跨模型比较。
    """
    normalized_query = _normalize_query(query)
    safe_top_k = _validate_top_k(top_k)
    safe_document_id = _validate_document_id(document_id)
    safe_min_score = _validate_min_score(min_score)

    if embedding_service is None:
        raise RetrievalError(
            "Embedding 服务尚未配置，无法执行检索。",
            code="embedding_not_configured",
            status_code=503,
        )

    dimension = embedding_service.dimension
    if (
        isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or dimension <= 0
        or dimension > MAX_VECTOR_DIMENSION
    ):
        raise RetrievalError(
            "Embedding 服务返回的向量维度配置无效。",
            code="invalid_embedding_dimension",
            status_code=500,
        )

    service_model = _normalize_model(embedding_service.model)

    try:
        raw_query_vector = await embedding_service.embed_query(normalized_query)
    except EmbeddingError as exc:
        raise _map_embedding_error(exc) from exc

    try:
        query_vector = validate_vector(
            raw_query_vector,
            dimension=dimension,
        )
    except VectorStoreError as exc:
        raise RetrievalError(
            "Embedding 服务返回的查询向量维度或数值不合法。",
            code="invalid_embedding_response",
            status_code=502,
        ) from exc

    return await search_similar_chunks(
        session,
        query_vector,
        top_k=safe_top_k,
        document_id=safe_document_id,
        model=service_model,
        min_score=safe_min_score,
    )


__all__ = [
    "MAX_TOP_K",
    "RetrievalError",
    "RetrievedChunk",
    "cosine_similarity",
    "search_chunks",
    "search_similar_chunks",
]
