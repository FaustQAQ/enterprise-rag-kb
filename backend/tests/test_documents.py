"""文档上传与解析接口测试。

测试文件全部在内存中生成，不依赖真实企业文档、数据库或外部网络服务。
"""

import io
from collections.abc import Iterator

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.core.config import get_settings
from app.main import app

client = TestClient(app)
PARSE_URL = "/api/v1/documents/parse"


def _build_docx(*paragraphs: str) -> bytes:
    """在内存中生成一个包含指定段落的 DOCX。"""
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_pdf(text: str) -> bytes:
    """在内存中生成一个包含单行文本的最小 PDF。

    不引入 reportlab 等额外测试依赖；直接按 PDF 语法写入一个使用
    Helvetica 字体的页面，pypdf 可以正常解析并提取文本。
    """
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


@pytest.fixture
def one_mb_upload_limit() -> Iterator[None]:
    """把上传上限临时降到 1 MB，快速验证超限分支。"""
    original_override = app.dependency_overrides.get(get_settings)
    limited_settings = get_settings().model_copy(
        update={"max_upload_size_mb": 1},
    )
    app.dependency_overrides[get_settings] = lambda: limited_settings

    try:
        yield
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_settings, None)
        else:
            app.dependency_overrides[get_settings] = original_override


def test_parse_valid_txt_returns_text() -> None:
    content = "企业知识库\n第二行内容"

    response = client.post(
        PARSE_URL,
        files={"file": ("notes.txt", content.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "notes.txt"
    assert payload["file_type"] == "txt"
    assert payload["text"] == content
    assert payload["character_count"] == len(content)
    assert "解析成功" in payload["message"]


def test_parse_txt_with_utf8_bom() -> None:
    response = client.post(
        PARSE_URL,
        files={
            "file": (
                "bom.txt",
                "\ufeff带 BOM 的文本".encode("utf-8"),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["text"] == "带 BOM 的文本"


def test_parse_valid_docx_extracts_paragraphs() -> None:
    data = _build_docx("第一段内容", "第二段内容")

    response = client.post(
        PARSE_URL,
        files={
            "file": (
                "policy.docx",
                data,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_type"] == "docx"
    assert payload["text"] == "第一段内容\n第二段内容"
    assert payload["character_count"] == len("第一段内容\n第二段内容")


def test_parse_valid_pdf_extracts_text() -> None:
    data = _build_pdf("Hello RAG PDF")

    response = client.post(
        PARSE_URL,
        files={"file": ("manual.pdf", data, "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_type"] == "pdf"
    assert "Hello RAG PDF" in payload["text"]


def test_parse_empty_file_returns_error() -> None:
    response = client.post(
        PARSE_URL,
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"
    assert "空" in response.json()["error"]["message"]


def test_parse_unsupported_extension_returns_error() -> None:
    response = client.post(
        PARSE_URL,
        files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_extension_takes_precedence_over_content_type() -> None:
    """扩展名是解析依据，客户端伪造的 Content-Type 不应改变处理方式。"""
    response = client.post(
        PARSE_URL,
        files={
            "file": (
                "notes.txt",
                "扩展名优先".encode("utf-8"),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["file_type"] == "txt"
    assert response.json()["text"] == "扩展名优先"


def test_missing_file_returns_unified_error() -> None:
    response = client.post(PARSE_URL)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "detail" not in response.json()


def test_parse_file_over_limit_returns_error(
    one_mb_upload_limit: None,
) -> None:
    oversized = b"x" * (1024 * 1024 + 1)

    response = client.post(
        PARSE_URL,
        files={"file": ("large.txt", oversized, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert "1 MB" in response.json()["error"]["message"]


def test_parse_invalid_pdf_returns_error() -> None:
    response = client.post(
        PARSE_URL,
        files={
            "file": (
                "broken.pdf",
                b"%PDF-1.4\nthis is not a valid pdf",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pdf"
    assert "无法解析" in response.json()["error"]["message"]


def test_parse_scanned_pdf_without_text_returns_error() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)

    response = client.post(
        PARSE_URL,
        files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "pdf_no_extractable_text"
    assert "扫描件" in payload["error"]["message"]


def test_parse_non_utf8_txt_returns_error() -> None:
    response = client.post(
        PARSE_URL,
        files={"file": ("gbk.txt", "中文".encode("gbk"), "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_text_encoding"


def test_filename_path_is_removed() -> None:
    response = client.post(
        PARSE_URL,
        files={
            "file": (
                "..\\..\\report.txt",
                "安全内容".encode("utf-8"),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "report.txt"


def test_openapi_contains_document_parse_route() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert PARSE_URL in response.json()["paths"]
