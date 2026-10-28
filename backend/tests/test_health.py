"""GET /health 健康检查接口测试。"""

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """健康检查应返回 200 和稳定的响应结构。"""
    settings = get_settings()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


def test_openapi_contains_health_route() -> None:
    """OpenAPI 文档中应包含 /health，方便联调和自动生成客户端。"""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
