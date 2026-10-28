"""FastAPI 应用入口。

在 backend 目录下启动：
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    DocumentEmbeddingError,
    DocumentParseError,
    DocumentPersistenceError,
    TextSplitError,
    document_embedding_error_handler,
    document_parse_error_handler,
    document_persistence_error_handler,
    request_validation_error_handler,
    text_split_error_handler,
)


def create_app() -> FastAPI:
    """应用工厂：便于测试创建独立实例，也方便后续扩展中间件。"""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="基于 RAG 的企业知识库问答系统后端 API。",
        debug=settings.debug,
    )

    if settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 文档解析、持久化和文本切分的业务异常统一转换为稳定的 JSON 错误结构。
    application.add_exception_handler(
        DocumentParseError,
        document_parse_error_handler,
    )
    application.add_exception_handler(
        DocumentPersistenceError,
        document_persistence_error_handler,
    )
    application.add_exception_handler(
        TextSplitError,
        text_split_error_handler,
    )
    application.add_exception_handler(
        DocumentEmbeddingError,
        document_embedding_error_handler,
    )
    # 请求参数校验失败也使用同一套错误结构。
    application.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )

    # 基础设施探针不挂版本前缀，便于直接访问 /health。
    application.include_router(health_router)

    # 业务 API 统一使用 /api/v1 前缀，文档解析等路由注册在 api_router 中。
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    return application


app = create_app()
