"""文本切分服务与 Chunk API 测试。

全部使用内存字符串，不访问数据库、网络或真实模型。
"""

from itertools import pairwise

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import TextSplitError
from app.main import app
from app.services.text_splitter import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    split_text,
)

client = TestClient(app)
CHUNK_URL = "/api/v1/documents/chunk"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\n\n\t  \r\n",
    ],
)
def test_blank_text_is_rejected(text: str) -> None:
    with pytest.raises(TextSplitError) as exc_info:
        split_text(text)

    assert exc_info.value.code == "empty_text"
    assert exc_info.value.status_code == 400
    assert "不能为空" in exc_info.value.message


def test_short_text_returns_one_chunk() -> None:
    text = "你好，RAG！"

    chunks = split_text(text)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.text == text
    assert chunk.character_count == len(text)
    assert chunk.start_index == 0
    assert chunk.end_index == len(text)


def test_long_text_preserves_order_and_overlap() -> None:
    text = "abcdefghij" * 120
    chunk_size = 200
    chunk_overlap = 20

    chunks = split_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.character_count <= chunk_size for chunk in chunks)
    assert all(chunk.text for chunk in chunks)
    assert chunks[0].start_index == 0
    assert chunks[-1].end_index == len(text)

    for previous, current in pairwise(chunks):
        assert previous.text[-chunk_overlap:] == current.text[:chunk_overlap]


def test_chinese_text_is_split_by_character_limit() -> None:
    text = "企业知识库问答系统需要把文档切分成合适的文本块。" * 50

    chunks = split_text(text, chunk_size=300, chunk_overlap=30)

    assert len(chunks) > 1
    assert all(chunk.character_count <= 300 for chunk in chunks)
    assert all(chunk.text.strip() == chunk.text for chunk in chunks)
    assert "企业知识库问答系统" in "".join(chunk.text for chunk in chunks)
    assert chunks[-1].end_index == len(text)


def test_zero_overlap_does_not_duplicate_text() -> None:
    text = "a" * 250

    chunks = split_text(text, chunk_size=100, chunk_overlap=0)

    assert [chunk.character_count for chunk in chunks] == [100, 100, 50]
    assert "".join(chunk.text for chunk in chunks) == text


def test_prefers_paragraph_boundary() -> None:
    first = "A" * 120
    second = "B" * 120
    third = "C" * 120
    text = f"{first}\n\n{second}\n\n{third}"

    chunks = split_text(text, chunk_size=200, chunk_overlap=20)

    assert chunks[0].text == first
    assert chunks[0].end_index == len(first)
    assert chunks[1].start_index == len(first) - 20
    assert chunks[1].text.startswith("A" * 20 + "\n\n")
    assert chunks[1].text.endswith(second)
    assert chunks[-1].end_index == len(text)


def test_prefers_sentence_boundary_for_long_paragraph() -> None:
    text = "这是一个句子。" * 100

    chunks = split_text(text, chunk_size=200, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(chunk.text.endswith("。") for chunk in chunks)
    assert all(chunk.character_count <= 200 for chunk in chunks)


def test_text_without_any_boundary_terminates() -> None:
    text = "x" * 1000

    chunks = split_text(text, chunk_size=137, chunk_overlap=17)

    assert 1 < len(chunks) < 100
    assert all(chunk.character_count <= 137 for chunk in chunks)
    assert chunks[-1].end_index == len(text)
    assert chunks[-1].text == text[chunks[-1].start_index:]


def test_chunks_are_not_whitespace_only() -> None:
    text = (
        "第一段内容" * 80
        + "\n\n \n\n"
        + "第二段内容" * 80
        + "\n \n"
        + "第三段内容" * 80
    )

    chunks = split_text(text, chunk_size=150, chunk_overlap=15)

    assert len(chunks) > 1
    assert all(chunk.text.strip() == chunk.text for chunk in chunks)
    assert all(not chunk.text.isspace() for chunk in chunks)


def test_outer_whitespace_is_removed() -> None:
    chunks = split_text("  \n你好，世界。\n  ")

    assert len(chunks) == 1
    assert chunks[0].text == "你好，世界。"
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == len("你好，世界。")


def test_default_parameters_are_500_and_50() -> None:
    text = "a" * 1200

    chunks = split_text(text)

    assert DEFAULT_CHUNK_SIZE == 500
    assert DEFAULT_CHUNK_OVERLAP == 50
    assert [chunk.character_count for chunk in chunks] == [500, 500, 300]
    assert chunks[0].start_index == 0
    assert chunks[1].start_index == 450
    assert chunks[-1].end_index == 1200


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_invalid_chunk_size_is_rejected(chunk_size: int) -> None:
    with pytest.raises(TextSplitError) as exc_info:
        split_text("有效文本", chunk_size=chunk_size)

    assert exc_info.value.code == "invalid_chunk_size"
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("chunk_overlap", [-1, 100, 101])
def test_invalid_chunk_overlap_is_rejected(chunk_overlap: int) -> None:
    with pytest.raises(TextSplitError) as exc_info:
        split_text(
            "有效文本",
            chunk_size=100,
            chunk_overlap=chunk_overlap,
        )

    assert exc_info.value.code == "invalid_chunk_overlap"
    assert exc_info.value.status_code == 422


def test_output_is_stable() -> None:
    text = "稳定的切分结果。\n\n" + "第二段内容。" * 80

    first = split_text(text, chunk_size=120, chunk_overlap=12)
    second = split_text(text, chunk_size=120, chunk_overlap=12)

    assert first == second


def test_chunk_api_returns_chunks_and_statistics() -> None:
    text = "第一段。\n\n第二段内容。" * 20

    response = client.post(
        CHUNK_URL,
        json={
            "text": text,
            "chunk_size": 80,
            "chunk_overlap": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] == len(payload["chunks"])
    assert payload["chunk_count"] > 1
    assert payload["total_character_count"] == len(text)

    for index, chunk in enumerate(payload["chunks"]):
        assert chunk["chunk_index"] == index
        assert chunk["character_count"] == len(chunk["text"])
        assert chunk["start_index"] <= chunk["end_index"]
        assert chunk["text"]


def test_chunk_api_rejects_blank_text() -> None:
    response = client.post(CHUNK_URL, json={"text": "  \n\t "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_text"
    assert "detail" not in response.json()


def test_chunk_api_rejects_invalid_overlap() -> None:
    response = client.post(
        CHUNK_URL,
        json={
            "text": "有效文本",
            "chunk_size": 10,
            "chunk_overlap": 10,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_openapi_contains_chunk_route() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert CHUNK_URL in response.json()["paths"]
