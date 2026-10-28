"""基础设施健康检查接口。"""

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="服务健康检查",
    description=(
        "用于本地验收、容器探针和负载均衡健康检查。"
        "该接口不访问数据库或大模型，避免把外部依赖故障误判为服务不可用。"
    ),
)
async def health_check(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """返回服务的基础运行信息。"""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
