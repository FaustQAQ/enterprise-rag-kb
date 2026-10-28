"""文档向量化接口的响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class DocumentEmbedResponse(BaseModel):
    """一次文档向量化任务的结果。"""

    document_id: int = Field(ge=1, description="已向量化的文档 ID")
    chunk_count: int = Field(ge=1, description="文档文本块总数")
    embedded_count: int = Field(ge=1, description="本次写入或更新的向量数量")
    dimension: int = Field(ge=1, description="向量维度")
    model: str | None = Field(
        default=None,
        description="实际使用的 Embedding 模型名；未知时为 null",
    )
    status: Literal["completed"] = Field(
        default="completed",
        description="本次任务状态；只有全部向量保存成功才返回 completed",
    )
    message: str = Field(description="结果说明")


__all__ = ["DocumentEmbedResponse"]
