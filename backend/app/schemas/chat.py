"""RAG 问答接口的请求与响应模型。"""

import math
from typing import Any

from pydantic import BaseModel, Field, StrictInt, StrictStr, field_validator


def _strip_question(value: Any) -> Any:
    """清理问题文本，并在清理后拒绝空问题。"""
    if not isinstance(value, str):
        raise ValueError("question 必须是字符串。")
    question = value.strip()
    if not question:
        raise ValueError("question 不能为空。")
    return question


def _reject_non_finite_score(value: float | None) -> float | None:
    """相似度分数必须是有限数值。"""
    if value is not None and not math.isfinite(value):
        raise ValueError("score 或 min_score 必须是有限数值。")
    return value


class ChatRequest(BaseModel):
    """一次 RAG 问答请求。"""

    question: StrictStr = Field(description="用户问题；会去除首尾空白且不能为空")
    top_k: StrictInt = Field(default=5, ge=1, le=20, description="最多检索文本块数量，范围 1-20")
    document_id: StrictInt | None = Field(default=None, ge=1, description="可选的文档 ID")
    min_score: float | None = Field(default=None, ge=-1, le=1, description="最低余弦相似度，范围 -1 到 1")

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: Any) -> Any:
        return _strip_question(value)

    @field_validator("min_score", mode="before")
    @classmethod
    def reject_invalid_min_score(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("min_score 必须是有限数值。")
        return value

    @field_validator("min_score")
    @classmethod
    def validate_min_score_is_finite(cls, value: float | None) -> float | None:
        return _reject_non_finite_score(value)


class ChatSource(BaseModel):
    """生成回答时使用的单条引用来源。"""

    chunk_id: StrictInt = Field(ge=1, description="文本块 ID")
    document_id: StrictInt = Field(ge=1, description="所属文档 ID")
    chunk_index: StrictInt = Field(ge=0, description="文档内文本块序号")
    filename: StrictStr | None = Field(default=None, description="来源文档文件名")
    text: StrictStr = Field(min_length=1, description="引用文本")
    score: float = Field(ge=-1, le=1, description="相似度分数，范围 -1 到 1")

    @field_validator("score", mode="before")
    @classmethod
    def reject_boolean_score(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("score 必须是有限数值。")
        return value

    @field_validator("score")
    @classmethod
    def validate_score_is_finite(cls, value: float) -> float:
        return _reject_non_finite_score(value)  # type: ignore[return-value]


class ChatResponse(BaseModel):
    """RAG 问答接口响应，不包含原始向量或认证信息。"""

    question: StrictStr = Field(description="去除首尾空白后的问题")
    answer: StrictStr = Field(description="生成的回答")
    sources: list[ChatSource] = Field(default_factory=list, description="引用来源")

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: Any) -> Any:
        return _strip_question(value)


__all__ = ["ChatRequest", "ChatResponse", "ChatSource"]
