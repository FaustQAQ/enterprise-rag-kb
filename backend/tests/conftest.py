"""测试公共夹具：为数据库相关测试提供独立的临时 SQLite 数据库。"""

from collections.abc import AsyncIterator, Iterator
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def sqlite_session_factory(
    tmp_path: Path,
) -> Iterator[async_sessionmaker[AsyncSession]]:
    """每个测试使用独立的临时 SQLite 文件，避免污染开发数据库。"""
    database_path = tmp_path / "test_rag.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    # NullPool 避免把某个事件循环创建的连接复用到 TestClient 的线程事件循环。
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())

    try:
        yield session_factory
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def db_client(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> Iterator[TestClient]:
    """覆盖 get_db 依赖，让 API 使用测试数据库。"""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sqlite_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
