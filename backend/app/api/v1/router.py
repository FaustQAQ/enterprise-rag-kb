"""v1 版本 API 聚合路由。

后续的 RAG 业务接口统一注册到这里，例如：
- POST /api/v1/documents/parse
- POST /api/v1/chat
"""

from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.retrieval import router as retrieval_router

api_router = APIRouter()
api_router.include_router(documents_router)
api_router.include_router(retrieval_router)
api_router.include_router(chat_router)
