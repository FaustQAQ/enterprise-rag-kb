"""数据库持久化文档的响应模型。"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.document import FileType


def _as_utc(value: datetime) -> datetime:
    """让 SQLite（无时区）和 PostgreSQL（有时区）返回一致的时间格式。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DocumentChunkRecord(BaseModel):
    """从数据库返回的文本块。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(ge=1, description="文本块主键")
    chunk_index: int = Field(ge=0, description="文档内从 0 开始的序号")
    text: str = Field(min_length=1, description="文本块内容")
    character_count: int = Field(ge=1, description="文本块字符数")
    start_index: int = Field(ge=0, description="规范化原文起始下标（包含）")
    end_index: int = Field(ge=0, description="规范化原文结束下标（不包含）")
    created_at: datetime = Field(description="创建时间")

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """把从 SQLite 读出的 naive datetime 视为 UTC。"""
        return _as_utc(value)


class DocumentSummaryResponse(BaseModel):
    """文档列表中的摘要信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(ge=1, description="文档主键")
    filename: str = Field(description="清洗后的文件名")
    file_type: FileType = Field(description="文件类型：pdf、docx 或 txt")
    character_count: int = Field(ge=1, description="解析出的字符数")
    status: str = Field(description="处理状态，本阶段固定为 processed")
    chunk_count: int = Field(ge=1, description="关联文本块数量")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """统一列表和详情响应中的时区表示。"""
        return _as_utc(value)


class DocumentDetailResponse(DocumentSummaryResponse):
    """文档详情，包含全部文本块。"""

    chunks: list[DocumentChunkRecord] = Field(description="按 chunk_index 排序的文本块")


class DocumentListResponse(BaseModel):
    """文档列表响应。"""

    items: list[DocumentSummaryResponse] = Field(description="文档摘要列表")
    total: int = Field(ge=0, description="文档总数")


class DeleteDocumentResponse(BaseModel):
    """删除文档后的响应。"""

    document_id: int = Field(ge=1, description="被删除的文档 ID")
    message: str = Field(description="删除结果说明")


__all__ = [
    "DeleteDocumentResponse",
    "DocumentChunkRecord",
    "DocumentDetailResponse",
    "DocumentListResponse",
    "DocumentSummaryResponse",
]
