"""文本块向量的持久化服务。

向量以 JSON 数组保存在独立的 ``document_chunk_embeddings`` 表中，因此 SQLite
和 PostgreSQL 都可以直接使用，不依赖 pgvector。仓储层只负责校验、读写和事务，
不调用任何 Embedding 外部服务；向量生成由 ``document_embedding`` 编排。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import VectorStoreError
from app.models.document import DocumentChunk, DocumentChunkEmbedding

logger = logging.getLogger(__name__)

MAX_VECTOR_DIMENSION = 65536
MAX_MODEL_NAME_LENGTH = 255


@dataclass(frozen=True, slots=True)
class EmbeddingWrite:
    """待写入的一条向量。

    调用方必须显式提供 ``dimension``，仓储会再次校验向量长度，避免把来源不明
    或维度不一致的数组写入数据库。
    """

    chunk_id: int
    vector: Sequence[float]
    dimension: int
    model: str | None = None


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    """从数据库读出的向量及其元数据。"""

    chunk_id: int
    vector: list[float]
    dimension: int
    model: str | None
    created_at: datetime
    updated_at: datetime


def _validate_dimension(dimension: object) -> int:
    """校验向量维度是合理的正整数。"""
    if (
        isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or dimension <= 0
        or dimension > MAX_VECTOR_DIMENSION
    ):
        raise VectorStoreError(
            f"向量维度必须是 1 到 {MAX_VECTOR_DIMENSION} 之间的整数。",
            code="invalid_vector_dimension",
            status_code=422,
        )
    return dimension


def _validate_chunk_id(chunk_id: object) -> int:
    """校验文本块 ID 是正整数。"""
    if (
        isinstance(chunk_id, bool)
        or not isinstance(chunk_id, int)
        or chunk_id <= 0
    ):
        raise VectorStoreError(
            "文本块 ID 必须是正整数。",
            code="invalid_chunk_id",
            status_code=422,
        )
    return chunk_id


def _normalize_model(model: object) -> str | None:
    """清洗模型名；允许未知，但拒绝非字符串和过长名称。"""
    if model is None:
        return None
    if not isinstance(model, str):
        raise VectorStoreError(
            "Embedding 模型名必须是字符串或空值。",
            code="invalid_embedding_model",
            status_code=422,
        )
    normalized = model.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_MODEL_NAME_LENGTH:
        raise VectorStoreError(
            f"Embedding 模型名不能超过 {MAX_MODEL_NAME_LENGTH} 个字符。",
            code="invalid_embedding_model",
            status_code=422,
        )
    return normalized


def validate_vector(
    raw_vector: object,
    *,
    dimension: int,
) -> list[float]:
    """校验并规范化一条向量。

    只接受非空、长度等于 ``dimension`` 的有限数值数组。字符串、布尔值、
    NaN、Infinity 以及空数组都会抛出 ``VectorStoreError``。
    """
    expected_dimension = _validate_dimension(dimension)

    if isinstance(raw_vector, (str, bytes)) or not isinstance(
        raw_vector, Sequence
    ):
        raise VectorStoreError(
            "向量必须是数值数组。",
            code="invalid_vector",
            status_code=422,
        )
    if len(raw_vector) == 0:
        raise VectorStoreError(
            "向量不能为空。",
            code="invalid_vector",
            status_code=422,
        )
    if len(raw_vector) != expected_dimension:
        raise VectorStoreError(
            "向量维度不一致："
            f"期望 {expected_dimension}，实际 {len(raw_vector)}。",
            code="invalid_vector_dimension",
            status_code=422,
        )

    normalized: list[float] = []
    for value in raw_vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise VectorStoreError(
                "向量只能包含数值。",
                code="invalid_vector",
                status_code=422,
            )
        number = float(value)
        if not math.isfinite(number):
            raise VectorStoreError(
                "向量不能包含 NaN 或 Infinity。",
                code="invalid_vector",
                status_code=422,
            )
        normalized.append(number)
    return normalized


def _validate_write(item: EmbeddingWrite) -> tuple[int, int, list[float], str | None]:
    """校验一条待写入记录，返回数据库需要的字段。"""
    if not isinstance(item, EmbeddingWrite):
        raise VectorStoreError(
            "批量写入项必须是 EmbeddingWrite。",
            code="invalid_vector_write",
            status_code=422,
        )
    chunk_id = _validate_chunk_id(item.chunk_id)
    dimension = _validate_dimension(item.dimension)
    vector = validate_vector(item.vector, dimension=dimension)
    model = _normalize_model(item.model)
    return chunk_id, dimension, vector, model


def _to_stored(record: DocumentChunkEmbedding) -> StoredEmbedding:
    """把 ORM 记录转换为不可变结果，并验证库内数据仍然合法。"""
    try:
        vector = validate_vector(record.vector, dimension=record.dimension)
    except VectorStoreError as exc:
        # 数据库被手工修改或历史数据损坏时，不用 422 把问题伪装成客户端错误。
        raise VectorStoreError(
            "已存储的向量格式无效，无法读取。",
            code="invalid_stored_vector",
            status_code=500,
        ) from exc

    return StoredEmbedding(
        chunk_id=record.chunk_id,
        vector=vector,
        dimension=record.dimension,
        model=record.model,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _storage_error(
    *,
    operation: str,
    exc: Exception,
    code: str,
    status_code: int,
    message: str,
) -> VectorStoreError:
    """只记录异常类型，不记录 SQL 参数、向量值或文本内容。"""
    logger.error("%s失败，数据库异常类型=%s", operation, type(exc).__name__)
    return VectorStoreError(message, code=code, status_code=status_code)


async def save_embeddings(
    session: AsyncSession,
    items: Sequence[EmbeddingWrite],
) -> int:
    """在单个事务中批量插入或更新向量，返回写入数量。

    所有输入先完整校验，再检查文本块是否存在；任意一条失败都会回滚，不会
    出现“部分成功却返回整体成功”的情况。一个文本块最多一条向量记录，重复
    调用会覆盖旧向量和元数据。
    """
    if not isinstance(items, Sequence):
        raise VectorStoreError(
            "批量向量数据必须是序列。",
            code="invalid_vector_write",
            status_code=422,
        )
    if not items:
        return 0

    normalized: dict[int, tuple[list[float], int, str | None]] = {}
    for item in items:
        chunk_id, dimension, vector, model = _validate_write(item)
        if chunk_id in normalized:
            raise VectorStoreError(
                f"同一批次中文本块 ID {chunk_id} 重复。",
                code="duplicate_chunk_id",
                status_code=422,
            )
        normalized[chunk_id] = (vector, dimension, model)

    chunk_ids = list(normalized)
    try:
        existing_chunk_ids = set(
            await session.scalars(
                select(DocumentChunk.id).where(DocumentChunk.id.in_(chunk_ids))
            )
        )
        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in existing_chunk_ids]
        if missing:
            await session.rollback()
            raise VectorStoreError(
                "部分文本块不存在，无法保存向量。",
                code="chunk_not_found",
                status_code=404,
            )

        records = {
            record.chunk_id: record
            for record in await session.scalars(
                select(DocumentChunkEmbedding).where(
                    DocumentChunkEmbedding.chunk_id.in_(chunk_ids)
                )
            )
        }

        for chunk_id, (vector, dimension, model) in normalized.items():
            record = records.get(chunk_id)
            if record is None:
                session.add(
                    DocumentChunkEmbedding(
                        chunk_id=chunk_id,
                        vector=vector,
                        dimension=dimension,
                        model=model,
                    )
                )
            else:
                # 覆盖旧向量时保持同一事务，失败则保留旧数据。
                record.vector = vector
                record.dimension = dimension
                record.model = model

        await session.commit()
        return len(normalized)
    except VectorStoreError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise _storage_error(
            operation="保存文本块向量",
            exc=exc,
            code="vector_conflict",
            status_code=409,
            message="向量保存失败：文本块或向量记录冲突，请重试。",
        ) from None
    except OperationalError as exc:
        await session.rollback()
        raise _storage_error(
            operation="保存文本块向量",
            exc=exc,
            code="database_unavailable",
            status_code=503,
            message="数据库暂时不可用，请稍后重试。",
        ) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _storage_error(
            operation="保存文本块向量",
            exc=exc,
            code="database_error",
            status_code=500,
            message="向量保存失败，请稍后重试。",
        ) from None


async def get_embedding(
    session: AsyncSession,
    chunk_id: int,
) -> StoredEmbedding | None:
    """按文本块 ID 查询向量；没有记录时返回 None。"""
    safe_id = _validate_chunk_id(chunk_id)
    try:
        record = await session.get(DocumentChunkEmbedding, safe_id)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _storage_error(
            operation="查询文本块向量",
            exc=exc,
            code="database_error",
            status_code=500,
            message="查询向量失败，请稍后重试。",
        ) from None

    if record is None:
        return None
    return _to_stored(record)


async def has_embedding(session: AsyncSession, chunk_id: int) -> bool:
    """检查文本块是否已经有向量。"""
    safe_id = _validate_chunk_id(chunk_id)
    try:
        existing = await session.scalar(
            select(DocumentChunkEmbedding.chunk_id).where(
                DocumentChunkEmbedding.chunk_id == safe_id
            )
        )
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _storage_error(
            operation="检查文本块向量",
            exc=exc,
            code="database_error",
            status_code=500,
            message="检查向量状态失败，请稍后重试。",
        ) from None
    return existing is not None


async def get_embeddings_for_document(
    session: AsyncSession,
    document_id: int,
) -> list[StoredEmbedding]:
    """按文本块顺序返回一份文档的全部向量。"""
    safe_id = _validate_chunk_id(document_id)
    try:
        records = await session.scalars(
            select(DocumentChunkEmbedding)
            .join(
                DocumentChunk,
                DocumentChunk.id == DocumentChunkEmbedding.chunk_id,
            )
            .where(DocumentChunk.document_id == safe_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return [_to_stored(record) for record in records]
    except VectorStoreError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _storage_error(
            operation="查询文档向量",
            exc=exc,
            code="database_error",
            status_code=500,
            message="查询文档向量失败，请稍后重试。",
        ) from None


__all__ = [
    "EmbeddingWrite",
    "MAX_MODEL_NAME_LENGTH",
    "MAX_VECTOR_DIMENSION",
    "StoredEmbedding",
    "get_embedding",
    "get_embeddings_for_document",
    "has_embedding",
    "save_embeddings",
    "validate_vector",
]
