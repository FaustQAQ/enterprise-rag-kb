"""文档与文本块的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。

    使用 Python 侧默认值，保证 SQLite 测试库和 PostgreSQL 都能在提交后
    立即拿到时间字段；同时保留 server_default 以兼容直接执行 SQL 的场景。
    """
    return datetime.now(timezone.utc)


class Document(Base):
    """一份已完成解析和切分的知识库文档。"""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "character_count >= 1",
            name="ck_documents_character_count_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="processed",
        server_default="processed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_index",
        lazy="selectin",
    )

    @property
    def chunk_count(self) -> int:
        """文本块数量；查询时通过 selectin 加载，避免异步懒加载。"""
        return len(self.chunks)


class DocumentChunk(Base):
    """文档切分后的单个文本块。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_index_non_negative",
        ),
        CheckConstraint(
            "character_count >= 1",
            name="ck_document_chunks_character_count_positive",
        ),
        CheckConstraint(
            "start_index >= 0",
            name="ck_document_chunks_start_index_non_negative",
        ),
        CheckConstraint(
            "end_index > start_index",
            name="ck_document_chunks_end_after_start",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_index: Mapped[int] = mapped_column(Integer, nullable=False)
    end_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
    embedding: Mapped[DocumentChunkEmbedding | None] = relationship(
        back_populates="chunk",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
        # 详情接口不需要返回完整向量；禁止隐式异步懒加载，按需由向量仓储查询。
        lazy="raise",
    )


class DocumentChunkEmbedding(Base):
    """文本块对应的向量记录。

    向量以 JSON 数组保存，因此同一套模型可以运行在 SQLite 和 PostgreSQL 上，
    不依赖 pgvector 扩展，也不绑定某个 Embedding 供应商。将来切换 pgvector
    时可以在迁移中把 ``vector`` 转换为 ``Vector(dimension)``，业务接口不变。
    """

    __tablename__ = "document_chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "dimension > 0",
            name="ck_document_chunk_embeddings_dimension_positive",
        ),
    )

    # 一个文本块最多一条向量记录；chunk_id 同时作为主键和外键。
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # 记录生成该向量的真实模型名，避免不同模型向量被静默混用。
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embedding")


__all__ = ["Document", "DocumentChunk", "DocumentChunkEmbedding"]
