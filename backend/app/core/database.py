"""数据库连接与会话管理。

创建异步引擎和会话工厂；建表由 ``scripts.init_db`` 负责，
业务代码通过 ``get_db`` 获取 AsyncSession。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# create_async_engine 是惰性的：导入本模块时不会真正连接数据库。
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：为每个请求提供一个异步数据库会话。

    事务提交由具体的 service 层决定；发生异常时统一回滚。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
