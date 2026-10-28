"""向量仓储的单元测试：序列化、校验、事务和级联删除。"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import VectorStoreError
from app.models.document import DocumentChunk, DocumentChunkEmbedding
from app.services.document_store import delete_document, save_document
from app.services.vector_store import (
    EmbeddingWrite,
    get_embedding,
    get_embeddings_for_document,
    has_embedding,
    save_embeddings,
    validate_vector,
)

VectorFactory = async_sessionmaker[AsyncSession]


def _seed_document(
    session_factory: VectorFactory,
    *,
    text: str = "第一段内容。\n\n第二段内容。",
) -> tuple[int, list[int]]:
    """保存一份至少包含两个文本块的文档，返回 ID 和块 ID。"""

    async def run() -> tuple[int, list[int]]:
        async with session_factory() as session:
            document = await save_document(
                session,
                filename="向量测试.txt",
                file_type="txt",
                text=text,
                chunk_size=12,
                chunk_overlap=0,
            )
            return document.id, [chunk.id for chunk in document.chunks]

    return asyncio.run(run())


def _run_save(
    session_factory: VectorFactory,
    chunk_ids: Sequence[int],
    *,
    dimension: int = 4,
    model: str | None = "test-embedding",
) -> int:
    """为给定文本块写入确定性的测试向量。"""

    async def run() -> int:
        async with session_factory() as session:
            items = [
                EmbeddingWrite(
                    chunk_id=chunk_id,
                    vector=[float(chunk_id), 0.5, -1.0, 2.0][:dimension],
                    dimension=dimension,
                    model=model,
                )
                for chunk_id in chunk_ids
            ]
            return await save_embeddings(session, items)

    return asyncio.run(run())


def test_validate_vector_accepts_finite_numeric_values() -> None:
    """JSON 反序列化后的整数/浮点数都应规范化为 float。"""
    assert validate_vector([1, 2.5, -3], dimension=3) == [1.0, 2.5, -3.0]


@pytest.mark.parametrize(
    ("raw_vector", "dimension", "code"),
    [
        ([], 4, "invalid_vector"),
        ([1.0, 2.0, 3.0], 4, "invalid_vector_dimension"),
        (["1.0", 2.0, 3.0, 4.0], 4, "invalid_vector"),
        ([True, 2.0, 3.0, 4.0], 4, "invalid_vector"),
        ([math.nan, 2.0, 3.0, 4.0], 4, "invalid_vector"),
        ([math.inf, 2.0, 3.0, 4.0], 4, "invalid_vector"),
        ("1234", 4, "invalid_vector"),
        (None, 4, "invalid_vector"),
    ],
)
def test_validate_vector_rejects_invalid_data(
    raw_vector: object,
    dimension: int,
    code: str,
) -> None:
    with pytest.raises(VectorStoreError) as exc_info:
        validate_vector(raw_vector, dimension=dimension)
    assert exc_info.value.code == code
    assert exc_info.value.status_code == 422


def test_save_and_read_embedding(
    sqlite_session_factory: VectorFactory,
) -> None:
    document_id, chunk_ids = _seed_document(sqlite_session_factory)
    assert len(chunk_ids) >= 2
    vector = [0.25, 0.5, 0.75, 1.0]

    async def run() -> None:
        async with sqlite_session_factory() as session:
            saved = await save_embeddings(
                session,
                [
                    EmbeddingWrite(
                        chunk_id=chunk_ids[0],
                        vector=vector,
                        dimension=4,
                        model="test-embedding",
                    )
                ],
            )
            assert saved == 1

            stored = await get_embedding(session, chunk_ids[0])
            assert stored is not None
            assert stored.chunk_id == chunk_ids[0]
            assert stored.vector == vector
            assert stored.dimension == 4
            assert stored.model == "test-embedding"
            assert await has_embedding(session, chunk_ids[0]) is True
            assert await has_embedding(session, chunk_ids[1]) is False

            all_vectors = await get_embeddings_for_document(session, document_id)
            assert [item.chunk_id for item in all_vectors] == [chunk_ids[0]]

    asyncio.run(run())


def test_save_embeddings_batch_and_update(
    sqlite_session_factory: VectorFactory,
) -> None:
    document_id, chunk_ids = _seed_document(sqlite_session_factory)

    assert _run_save(sqlite_session_factory, chunk_ids) == len(chunk_ids)

    async def read_vectors() -> list[list[float]]:
        async with sqlite_session_factory() as session:
            stored = await get_embeddings_for_document(session, document_id)
            return [item.vector for item in stored]

    first = asyncio.run(read_vectors())
    assert len(first) == len(chunk_ids)

    # 再次保存应覆盖旧向量，而不是新增重复记录。
    updated = [
        EmbeddingWrite(
            chunk_id=chunk_id,
            vector=[float(chunk_id), 9.0, 8.0, 7.0],
            dimension=4,
            model="test-embedding-v2",
        )
        for chunk_id in chunk_ids
    ]

    async def overwrite() -> int:
        async with sqlite_session_factory() as session:
            return await save_embeddings(session, updated)

    assert asyncio.run(overwrite()) == len(chunk_ids)

    async def count_rows() -> int:
        async with sqlite_session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(DocumentChunkEmbedding)
                )
                or 0
            )

    assert asyncio.run(count_rows()) == len(chunk_ids)
    assert asyncio.run(read_vectors())[0] == [float(chunk_ids[0]), 9.0, 8.0, 7.0]


def test_save_embeddings_rejects_missing_chunk(
    sqlite_session_factory: VectorFactory,
) -> None:
    async def run() -> None:
        async with sqlite_session_factory() as session:
            with pytest.raises(VectorStoreError) as exc_info:
                await save_embeddings(
                    session,
                    [EmbeddingWrite(chunk_id=999999, vector=[1.0] * 4, dimension=4)],
                )
            assert exc_info.value.code == "chunk_not_found"
            assert exc_info.value.status_code == 404

    asyncio.run(run())


def test_save_embeddings_rejects_duplicate_chunk_in_batch(
    sqlite_session_factory: VectorFactory,
) -> None:
    _, chunk_ids = _seed_document(sqlite_session_factory)
    item = EmbeddingWrite(chunk_id=chunk_ids[0], vector=[1.0] * 4, dimension=4)

    async def run() -> None:
        async with sqlite_session_factory() as session:
            with pytest.raises(VectorStoreError) as exc_info:
                await save_embeddings(session, [item, item])
            assert exc_info.value.code == "duplicate_chunk_id"

    asyncio.run(run())


def test_save_embeddings_rolls_back_on_commit_failure(
    sqlite_session_factory: VectorFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id, chunk_ids = _seed_document(sqlite_session_factory)

    async def failing_commit(self: AsyncSession) -> None:
        # 模拟数据库在写入后、提交时不可用。
        raise OperationalError("COMMIT", {}, Exception("database unavailable"))

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    async def run() -> None:
        async with sqlite_session_factory() as session:
            with pytest.raises(VectorStoreError) as exc_info:
                await save_embeddings(
                    session,
                    [
                        EmbeddingWrite(
                            chunk_id=chunk_id,
                            vector=[1.0, 2.0, 3.0, 4.0],
                            dimension=4,
                        )
                        for chunk_id in chunk_ids
                    ],
                )
            assert exc_info.value.code == "database_unavailable"
            assert exc_info.value.status_code == 503

            # 回滚后不能留下部分记录。
            remaining = await get_embeddings_for_document(session, document_id)
            assert remaining == []

    asyncio.run(run())


def test_delete_document_removes_embeddings_and_chunks(
    sqlite_session_factory: VectorFactory,
) -> None:
    document_id, chunk_ids = _seed_document(sqlite_session_factory)
    _run_save(sqlite_session_factory, chunk_ids)

    async def run() -> None:
        async with sqlite_session_factory() as session:
            await delete_document(session, document_id)
            embedding_count = await session.scalar(
                select(func.count()).select_from(DocumentChunkEmbedding)
            )
            chunk_count = await session.scalar(
                select(func.count()).select_from(DocumentChunk)
            )
            assert int(embedding_count or 0) == 0
            assert int(chunk_count or 0) == 0

    asyncio.run(run())
