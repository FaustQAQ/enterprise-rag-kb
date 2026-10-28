"""文档与文本块的数据库持久化服务。

本模块只负责业务数据和事务，不处理 HTTP 请求。所有写操作都通过
调用方传入的 AsyncSession 完成；成功时由本模块提交事务，失败时回滚。
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentPersistenceError
from app.models.document import Document, DocumentChunk, DocumentChunkEmbedding
from app.services.text_splitter import split_text

logger = logging.getLogger(__name__)


def _persistence_error(
    *,
    operation: str,
    exc: Exception,
    code: str,
    status_code: int,
    message: str,
) -> DocumentPersistenceError:
    """记录数据库异常类型，但不记录 SQL 参数或文档正文。"""
    logger.error("%s失败，数据库异常类型=%s", operation, type(exc).__name__)
    return DocumentPersistenceError(message, code=code, status_code=status_code)


async def save_document(
    session: AsyncSession,
    *,
    filename: str,
    file_type: str,
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> Document:
    """在一个事务中保存文档及其全部文本块。

    Args:
        session: 请求级异步数据库会话。
        filename: 已清洗的文件名。
        file_type: pdf、docx 或 txt。
        text: 解析后的全文，切分器会统一换行并去除首尾空白。
        chunk_size: 单块最大字符数。
        chunk_overlap: 相邻块重叠字符数。

    Raises:
        TextSplitError: 文本为空或切分参数不合法。
        DocumentPersistenceError: 数据库写入失败。
    """
    safe_filename = filename.strip()
    if not safe_filename:
        raise DocumentPersistenceError(
            "文件名不能为空。",
            code="invalid_document",
            status_code=422,
        )

    # 切分失败时不会向 session 添加任何对象，因此不会留下半条记录。
    chunks = split_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    document = Document(
        filename=safe_filename,
        file_type=file_type,
        # 保留解析结果本身的字符数；块的 start/end 基于规范化文本。
        character_count=len(text),
        status="processed",
        chunks=[
            DocumentChunk(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                character_count=chunk.character_count,
                start_index=chunk.start_index,
                end_index=chunk.end_index,
            )
            for chunk in chunks
        ],
    )

    try:
        session.add(document)
        # 一次 commit 同时写入 documents 和 document_chunks。
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="保存文档",
            exc=exc,
            code="document_conflict",
            status_code=409,
            message="文档保存失败：文本块序号冲突，请重试。",
        ) from None
    except OperationalError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="保存文档",
            exc=exc,
            code="database_unavailable",
            status_code=503,
            message="数据库暂时不可用，请稍后重试。",
        ) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="保存文档",
            exc=exc,
            code="database_error",
            status_code=500,
            message="文档保存失败，请稍后重试。",
        ) from None

    # 使用 expire_on_commit=False 的会话，commit 后对象仍然可读，无需 refresh。
    return document


async def list_documents(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Document], int]:
    """按创建顺序倒序分页查询文档，并返回总数。"""
    try:
        total = await session.scalar(select(func.count()).select_from(Document))
        result = await session.scalars(
            select(Document)
            .order_by(Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result), int(total or 0)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="查询文档列表",
            exc=exc,
            code="database_error",
            status_code=500,
            message="查询文档列表失败，请稍后重试。",
        ) from None


async def get_document(
    session: AsyncSession,
    document_id: int,
) -> Document:
    """按主键查询文档；不存在时抛出 404 业务异常。"""
    try:
        document = await session.get(Document, document_id)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="查询文档详情",
            exc=exc,
            code="database_error",
            status_code=500,
            message="查询文档详情失败，请稍后重试。",
        ) from None

    if document is None:
        raise DocumentPersistenceError(
            "文档不存在。",
            code="document_not_found",
            status_code=404,
        )
    return document


async def delete_document(
    session: AsyncSession,
    document_id: int,
) -> None:
    """删除指定文档及其关联文本块和向量。

    先按 document_id 显式删除文本块向量和文本块，再按主键删除文档本身。
    这里使用 Core DELETE 而不是 ORM 级联，避免已加载的 relationship 在批量
    删除时产生额外的逐行 DELETE；所有语句都在同一个事务中提交。SQLite 默认
    不启用外键级联，因此不能只依赖数据库的 ON DELETE CASCADE。
    """
    try:
        existing_id = await session.scalar(
            select(Document.id).where(Document.id == document_id)
        )
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="删除文档",
            exc=exc,
            code="database_error",
            status_code=500,
            message="删除文档失败，请稍后重试。",
        ) from None

    if existing_id is None:
        raise DocumentPersistenceError(
            "文档不存在。",
            code="document_not_found",
            status_code=404,
        )

    try:
        # 先删向量，再删文本块；WHERE 子查询严格限定目标文档。
        # SQLite 默认不强制外键，显式删除可避免留下孤立向量。
        await session.execute(
            delete(DocumentChunkEmbedding).where(
                DocumentChunkEmbedding.chunk_id.in_(
                    select(DocumentChunk.id).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            )
        )
        # WHERE 条件严格限定目标文档，绝不按其他条件批量删除。
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await session.execute(
            delete(Document).where(Document.id == document_id)
        )
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise _persistence_error(
            operation="删除文档",
            exc=exc,
            code="database_error",
            status_code=500,
            message="删除文档失败，请稍后重试。",
        ) from None


__all__ = [
    "delete_document",
    "get_document",
    "list_documents",
    "save_document",
]
