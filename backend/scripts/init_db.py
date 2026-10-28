"""创建当前阶段所需的数据库表。

用法（在 backend 目录下）：
    python -m scripts.init_db

脚本只执行 ``Base.metadata.create_all``，不会删除、覆盖或重建已有表，也不会
清空文档数据。默认使用 SQLite（DATABASE_URL=sqlite+aiosqlite:///./rag_kb.db）；
如通过 DATABASE_URL 指定 PostgreSQL，需要先创建目标库。
自动化测试使用独立的临时 SQLite 文件，不会执行本脚本。
"""

import asyncio

from app.core.database import async_engine
from app.models import Base


async def init_db() -> None:
    """创建 documents、document_chunks 和 document_chunk_embeddings 表。"""
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())
