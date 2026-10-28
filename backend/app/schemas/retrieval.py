"""检索 HTTP 接口的请求与响应模型。"""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class RetrievalSearchRequest(BaseModel):
    """一次文本块检索请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "公司的考勤制度是什么？",
                "top_k": 5,
                "document_id": None,
                "min_score": None,
            }
        }
    )

    query: str = Field(
        description="用于检索的自然语言查询；不能为空或只包含空白字符",
    )
    top_k: StrictInt = Field(
        default=5,
        ge=1,
        le=100,
        description="最多返回的命中数量，范围 1-100",
    )
    document_id: StrictInt | None = Field(
        default=None,
        ge=1,
        description="可选的文档 ID；只检索该文档的文本块",
    )
    min_score: float | None = Field(
        default=None,
        ge=-1,
        le=1,
        description="可选的最低余弦相似度，范围 -1 到 1",
    )

    @field_validator("min_score", mode="before")
    @classmethod
    def reject_boolean_min_score(cls, value: object) -> object:
        """布尔值在 Python 中是 int 子类，不能当作相似度阈值。"""
        if isinstance(value, bool):
            raise ValueError("min_score 必须是 -1 到 1 之间的数值。")
        return value


class RetrievalHit(BaseModel):
    """单条检索命中；不包含原始向量。"""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: int = Field(ge=1, description="文本块 ID")
    document_id: int = Field(ge=1, description="所属文档 ID")
    chunk_index: int = Field(ge=0, description="文档内文本块序号")
    text: str = Field(min_length=1, description="命中的文本块内容")
    score: float = Field(
        ge=-1,
        le=1,
        description="查询向量与文本块向量的余弦相似度",
    )
    model: str | None = Field(
        default=None,
        max_length=255,
        description="生成向量时记录的模型名；未知时为 null",
    )
    dimension: int = Field(ge=1, description="向量维度")


class RetrievalSearchResponse(BaseModel):
    """检索接口响应。"""

    query: str = Field(description="去除首尾空白后的查询文本")
    hits: list[RetrievalHit] = Field(description="按相似度降序排列的命中列表")


__all__ = [
    "RetrievalHit",
    "RetrievalSearchRequest",
    "RetrievalSearchResponse",
]
