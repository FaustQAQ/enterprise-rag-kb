"""RAG 问答 Pydantic Schema 的单元测试。"""

import math

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, ChatResponse, ChatSource


def test_chat_request_normalizes_question_and_uses_defaults() -> None:
    request = ChatRequest.model_validate({"question": "  考勤制度是什么？  "})
    assert request.question == "考勤制度是什么？"
    assert request.top_k == 5
    assert request.document_id is None
    assert request.min_score is None


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_chat_request_rejects_empty_question(question: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": question})


@pytest.mark.parametrize("question", [None, 123, True, [], {}])
def test_chat_request_rejects_non_string_question(question: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": question})


@pytest.mark.parametrize("top_k", [0, 21, True, 1.5])
def test_chat_request_rejects_invalid_top_k(top_k: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": "考勤", "top_k": top_k})


@pytest.mark.parametrize("document_id", [0, -1, True, 1.5])
def test_chat_request_rejects_invalid_document_id(document_id: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": "考勤", "document_id": document_id})


@pytest.mark.parametrize("min_score", [-1.1, 1.1, True, math.nan, math.inf, -math.inf])
def test_chat_request_rejects_invalid_min_score(min_score: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"question": "考勤", "min_score": min_score})


def test_chat_source_accepts_valid_fields_and_optional_filename() -> None:
    source = ChatSource.model_validate({"chunk_id": 3, "document_id": 2, "chunk_index": 0, "filename": None, "text": "员工应按规定打卡。", "score": 0.875})
    assert source.filename is None
    assert source.score == pytest.approx(0.875)


@pytest.mark.parametrize("payload", [{"chunk_id": 0}, {"document_id": 0}, {"chunk_index": -1}, {"text": ""}, {"score": -1.1}, {"score": 1.1}, {"score": True}, {"score": math.nan}, {"score": math.inf}])
def test_chat_source_rejects_invalid_fields(payload: dict[str, object]) -> None:
    valid_payload: dict[str, object] = {"chunk_id": 1, "document_id": 1, "chunk_index": 0, "filename": "考勤制度.txt", "text": "员工应按规定打卡。", "score": 0.8}
    valid_payload.update(payload)
    with pytest.raises(ValidationError):
        ChatSource.model_validate(valid_payload)


def test_chat_response_supports_empty_sources_and_normalizes_question() -> None:
    response = ChatResponse.model_validate({"question": "  考勤制度？  ", "answer": "请参考公司考勤制度。"})
    assert response.question == "考勤制度？"
    assert response.sources == []


def test_chat_response_model_validate_and_model_dump() -> None:
    response = ChatResponse.model_validate({"question": "  谁负责审批？ ", "answer": "部门负责人负责审批。", "sources": [{"chunk_id": 7, "document_id": 4, "chunk_index": 2, "filename": "流程手册.pdf", "text": "由部门负责人审批。", "score": 1.0}]})
    assert response.model_dump() == {"question": "谁负责审批？", "answer": "部门负责人负责审批。", "sources": [{"chunk_id": 7, "document_id": 4, "chunk_index": 2, "filename": "流程手册.pdf", "text": "由部门负责人审批。", "score": 1.0}]}
    assert "vector" not in response.model_dump_json()
    assert "api_key" not in response.model_dump_json().lower()
