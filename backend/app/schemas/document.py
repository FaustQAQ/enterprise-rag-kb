"""文档上传、解析与文本切分相关的请求 / 响应模型。"""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

FileType = Literal["pdf", "docx", "txt"]


class DocumentParseResponse(BaseModel):
    """POST /api/v1/documents/parse 的成功响应。"""

    filename: str = Field(description="去除路径后的原始文件名")
    file_type: FileType = Field(description="文件格式：pdf、docx 或 txt")
    character_count: int = Field(ge=1, description="提取文本的字符数")
    text: str = Field(description="提取出的纯文本内容")
    message: str = Field(description="处理结果说明")


class ChunkRequest(BaseModel):
    """POST /api/v1/documents/chunk 的请求体。"""

    text: str = Field(
        description="待切分的非空文本",
        examples=["企业知识库需要先把长文档切分成可检索的文本块。"],
    )
    chunk_size: int = Field(
        default=500,
        gt=0,
        description="单块最大字符数，按字符而非 token 计算",
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        description="相邻块的重叠字符数，必须小于 chunk_size",
    )

    @model_validator(mode="after")
    def validate_chunk_parameters(self) -> Self:
        """重叠长度必须小于块大小，否则无法保证切分向前推进。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size。")
        return self


class TextChunkResponse(BaseModel):
    """单个文本块。"""

    chunk_index: int = Field(ge=0, description="从 0 开始的稳定序号")
    text: str = Field(min_length=1, description="文本块内容")
    character_count: int = Field(ge=1, description="文本块字符数")
    start_index: int = Field(
        ge=0,
        description="在规范化源文本中的起始字符下标（包含）",
    )
    end_index: int = Field(
        ge=0,
        description="在规范化源文本中的结束字符下标（不包含）",
    )


class ChunkResponse(BaseModel):
    """POST /api/v1/documents/chunk 的成功响应。"""

    chunks: list[TextChunkResponse] = Field(description="按原文顺序排列的文本块")
    chunk_count: int = Field(ge=1, description="文本块数量")
    total_character_count: int = Field(
        ge=1,
        description="规范化后源文本的总字符数",
    )


class ErrorDetail(BaseModel):
    """统一错误响应中的错误详情。"""

    code: str = Field(description="稳定的机器可读错误码")
    message: str = Field(description="面向用户的中文错误提示")


class ErrorResponse(BaseModel):
    """统一错误响应体。"""

    error: ErrorDetail
