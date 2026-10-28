"""健康检查相关的响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """GET /health 的响应体。"""

    status: Literal["ok"] = Field(default="ok", description="服务状态")
    service: str = Field(description="服务名称")
    version: str = Field(description="服务版本")
    environment: str = Field(description="运行环境")
