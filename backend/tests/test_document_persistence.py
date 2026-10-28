"""文档持久化 API、事务和约束测试。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import DocumentPersistenceError
from app.models import Document, DocumentChunk
from app.services.document_store import save_document

SAMPLE_TEXT = (
    "第一段：企业知识库需要把制度、流程和产品资料统一管理。\n\n"
    "第二段：检索增强生成通过检索相关片段为问答提供依据。\n\n"
    "第三段：本阶段只验证文档和文本块的持久化，不生成向量。"
)


def _upload(
    client: TestClient,
    *,
    text: str = SAMPLE_TEXT,
    filename: str = "knowledge.txt",
    content_type: str = "text/plain",
    chunk_size: int = 40,
    chunk_overlap: int = 5,
):
    """调用上传入库接口，默认参数保证生成多个文本块。"""
    return client.post(
        "/api/v1/documents",
        files={"file": (filename, text.encode("utf-8"), content_type)},
        data={
            "chunk_size": str(chunk_size),
            "chunk_overlap": str(chunk_overlap),
        },
    )


async def _count_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int]:
    async with session_factory() as session:
        document_count = await session.scalar(
            select(func.count()).select_from(Document)
        )
        chunk_count = await session.scalar(
            select(func.count()).select_from(DocumentChunk)
        )
        return int(document_count or 0), int(chunk_count or 0)


async def _count_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: int,
) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return int(count or 0)


def test_save_document_with_multiple_chunks(db_client: TestClient) -> None:
    response = _upload(db_client)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["filename"] == "knowledge.txt"
    assert payload["file_type"] == "txt"
    assert payload["character_count"] == len(SAMPLE_TEXT)
    assert payload["status"] == "processed"
    assert payload["chunk_count"] >= 2
    assert payload["chunk_count"] == len(payload["chunks"])

    chunks = payload["chunks"]
    assert [chunk["chunk_index"] for chunk in chunks] == list(
        range(len(chunks))
    )
    assert all(chunk["character_count"] == len(chunk["text"]) for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)
    assert chunks[0]["start_index"] == 0
    assert chunks[-1]["end_index"] == len(SAMPLE_TEXT)


def test_document_list_and_detail(db_client: TestClient) -> None:
    first = _upload(db_client, filename="first.txt").json()
    second = _upload(db_client, filename="second.txt").json()

    list_response = db_client.get("/api/v1/documents")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 2
    assert {item["filename"] for item in list_payload["items"]} == {
        "first.txt",
        "second.txt",
    }
    # 列表只返回摘要，不携带完整文本块，避免响应过大。
    assert all("chunks" not in item for item in list_payload["items"])

    detail_response = db_client.get(
        f"/api/v1/documents/{second['id']}"
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == second["id"]
    assert detail_payload["filename"] == "second.txt"
    assert len(detail_payload["chunks"]) == second["chunk_count"]
    assert detail_payload["chunks"] == second["chunks"]
    assert first["id"] != second["id"]


def test_missing_document_returns_404(db_client: TestClient) -> None:
    get_response = db_client.get("/api/v1/documents/999999")
    delete_response = db_client.delete("/api/v1/documents/999999")

    assert get_response.status_code == 404
    assert get_response.json()["error"]["code"] == "document_not_found"
    assert delete_response.status_code == 404
    assert delete_response.json()["error"]["code"] == "document_not_found"


def test_delete_document_removes_only_its_chunks(
    db_client: TestClient,
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = _upload(db_client, filename="delete-me.txt").json()
    second = _upload(db_client, filename="keep-me.txt").json()

    delete_response = db_client.delete(f"/api/v1/documents/{first['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["document_id"] == first["id"]

    assert db_client.get(f"/api/v1/documents/{first['id']}").status_code == 404
    assert db_client.get(f"/api/v1/documents/{second['id']}").status_code == 200

    assert asyncio.run(_count_chunks(sqlite_session_factory, first["id"])) == 0
    assert asyncio.run(_count_chunks(sqlite_session_factory, second["id"])) == (
        second["chunk_count"]
    )


def test_transaction_failure_leaves_no_partial_records(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_flush = AsyncSession.flush

    async def failing_commit(self: AsyncSession) -> None:
        # 先真正 flush 文档和文本块，再模拟提交阶段的数据库故障。
        await original_flush(self)
        raise OperationalError(
            "simulated commit failure",
            {},
            Exception("simulated"),
        )

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    async def attempt_save() -> None:
        async with sqlite_session_factory() as session:
            with pytest.raises(DocumentPersistenceError) as exc_info:
                await save_document(
                    session,
                    filename="rollback.txt",
                    file_type="txt",
                    text=SAMPLE_TEXT,
                    chunk_size=40,
                    chunk_overlap=5,
                )
            assert exc_info.value.status_code == 503
            assert exc_info.value.code == "database_unavailable"

    asyncio.run(attempt_save())
    assert asyncio.run(_count_rows(sqlite_session_factory)) == (0, 0)


def test_chunk_index_is_unique_within_document(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def insert_duplicate_chunks() -> None:
        async with sqlite_session_factory() as session:
            document = Document(
                filename="duplicate.txt",
                file_type="txt",
                character_count=2,
                status="processed",
                chunks=[
                    DocumentChunk(
                        chunk_index=0,
                        text="a",
                        character_count=1,
                        start_index=0,
                        end_index=1,
                    ),
                    DocumentChunk(
                        chunk_index=0,
                        text="b",
                        character_count=1,
                        start_index=1,
                        end_index=2,
                    ),
                ],
            )
            session.add(document)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    asyncio.run(insert_duplicate_chunks())
    assert asyncio.run(_count_rows(sqlite_session_factory)) == (0, 0)


def test_empty_file_is_rejected_without_record(db_client: TestClient) -> None:
    response = db_client.post(
        "/api/v1/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"chunk_size": "40", "chunk_overlap": "5"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"
    assert db_client.get("/api/v1/documents").json()["total"] == 0


def test_invalid_chunk_parameters_are_rejected(db_client: TestClient) -> None:
    zero_size = _upload(db_client, chunk_size=0)
    bad_overlap = _upload(db_client, chunk_size=10, chunk_overlap=10)

    assert zero_size.status_code == 422
    assert zero_size.json()["error"]["code"] == "validation_error"
    assert bad_overlap.status_code == 422
    assert bad_overlap.json()["error"]["code"] == "invalid_chunk_overlap"
    assert db_client.get("/api/v1/documents").json()["total"] == 0


def test_unsupported_file_is_rejected_without_record(
    db_client: TestClient,
) -> None:
    response = db_client.post(
        "/api/v1/documents",
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
        data={"chunk_size": "40", "chunk_overlap": "5"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert db_client.get("/api/v1/documents").json()["total"] == 0
