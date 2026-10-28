"""文档解析服务。

职责边界：
- 只接收已经读取到内存中的文件字节，不处理 HTTP multipart。
- 不把上传文件写入本地磁盘。
- 负责扩展名校验、文件名清洗、TXT / PDF / DOCX 文本提取。

解析失败统一抛出 DocumentParseError，由 API 层转换成稳定的错误响应。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PureWindowsPath

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.core.exceptions import DocumentParseError

# 扩展名 -> 对外返回的文件类型。扩展名统一转小写后匹配。
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
}

# 常见文件系统对单个文件名长度的限制，避免异常长文件名进入响应。
MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """解析完成后的文档数据。"""

    filename: str
    file_type: str
    text: str

    @property
    def character_count(self) -> int:
        """返回提取文本的字符数（按 Unicode 码点计数）。"""
        return len(self.text)


def normalize_filename(raw_filename: str | None) -> str:
    """清洗客户端文件名，只保留最后一段文件名。

    同时处理 Windows 和 POSIX 风格的分隔符，避免 ``..\\..\\evil.txt``
    之类的路径进入后续逻辑。本阶段不会把文件写入磁盘，但文件名仍会
    出现在响应中，因此需要主动去除路径。
    """
    if raw_filename is None or not raw_filename.strip():
        raise DocumentParseError(
            "缺少文件名，请通过 multipart/form-data 上传文件。",
            code="missing_filename",
            status_code=400,
        )

    filename = raw_filename.strip()
    if "\x00" in filename:
        raise DocumentParseError(
            "文件名包含非法字符。",
            code="invalid_filename",
            status_code=400,
        )

    # PureWindowsPath 在 Windows / Linux 上都能识别反斜杠和正斜杠。
    basename = PureWindowsPath(filename).name.strip()
    if not basename or basename in {".", ".."}:
        raise DocumentParseError(
            "文件名无效，请重新选择文件。",
            code="invalid_filename",
            status_code=400,
        )

    if any(ord(char) < 32 or ord(char) == 127 for char in basename):
        raise DocumentParseError(
            "文件名包含控制字符。",
            code="invalid_filename",
            status_code=400,
        )

    if len(basename) > MAX_FILENAME_LENGTH:
        raise DocumentParseError(
            f"文件名过长，最多支持 {MAX_FILENAME_LENGTH} 个字符。",
            code="filename_too_long",
            status_code=400,
        )

    return basename


def detect_file_type(filename: str) -> str:
    """根据扩展名判断文件类型，不信任客户端提供的 Content-Type。"""
    suffix = PureWindowsPath(filename).suffix.lower()
    file_type = ALLOWED_EXTENSIONS.get(suffix)
    if file_type is None:
        raise DocumentParseError(
            "不支持的文件格式，仅支持 .pdf、.docx、.txt。",
            code="unsupported_file_type",
            status_code=415,
        )
    return file_type


def parse_document(filename: str | None, data: bytes) -> ParsedDocument:
    """解析文档字节并返回纯文本。

    Args:
        filename: 客户端提供的原始文件名，内部会做路径清洗。
        data: 已受大小限制保护的文件字节。

    Raises:
        DocumentParseError: 文件为空、格式不支持、编码错误或内容无法解析。
    """
    safe_filename = normalize_filename(filename)
    file_type = detect_file_type(safe_filename)

    if not data:
        raise DocumentParseError(
            "文件内容为空，请上传非空文件。",
            code="empty_file",
            status_code=400,
        )

    if file_type == "txt":
        text = _parse_txt(data)
    elif file_type == "pdf":
        text = _parse_pdf(data)
    else:
        text = _parse_docx(data)

    return ParsedDocument(
        filename=safe_filename,
        file_type=file_type,
        text=text,
    )


def _parse_txt(data: bytes) -> str:
    """按 UTF-8 解码 TXT，并统一换行符。"""
    try:
        # utf-8-sig 会同时兼容带 BOM 和不带 BOM 的 UTF-8 文件。
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentParseError(
            "TXT 文件必须使用 UTF-8 编码，当前文件无法按 UTF-8 解码。",
            code="invalid_text_encoding",
            status_code=422,
        ) from None

    text = _normalize_newlines(text)
    if not text.strip():
        raise DocumentParseError(
            "TXT 文件内容为空，请上传包含文本的文件。",
            code="empty_file",
            status_code=400,
        )
    return text


def _parse_pdf(data: bytes) -> str:
    """使用 pypdf 提取每一页的可读文本。"""
    try:
        reader = PdfReader(io.BytesIO(data))

        if reader.is_encrypted:
            raise DocumentParseError(
                "PDF 文件已加密，当前版本暂不支持加密文档。",
                code="encrypted_pdf",
                status_code=422,
            )

        pages: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            cleaned_text = page_text.strip()
            if cleaned_text:
                pages.append(cleaned_text)
    except DocumentParseError:
        raise
    except Exception:
        # 不把 pypdf 的内部异常和文件路径返回给客户端。
        raise DocumentParseError(
            "PDF 文件无法解析，文件可能已损坏或格式不受支持。",
            code="invalid_pdf",
            status_code=422,
        ) from None

    if not pages:
        raise DocumentParseError(
            "PDF 中未提取到文本，可能是扫描件或空白文档；"
            "当前版本暂不支持 OCR。",
            code="pdf_no_extractable_text",
            status_code=422,
        )

    return "\n\n".join(pages)


def _parse_docx(data: bytes) -> str:
    """使用 python-docx 提取正文段落文本。"""
    try:
        document = DocxDocument(io.BytesIO(data))
        paragraphs = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]
    except Exception:
        raise DocumentParseError(
            "DOCX 文件无法解析，文件可能已损坏或不是有效的 Word 文档。",
            code="invalid_docx",
            status_code=422,
        ) from None

    if not paragraphs:
        raise DocumentParseError(
            "DOCX 中未提取到文本内容，请确认文档正文包含文字。",
            code="docx_no_text",
            status_code=422,
        )

    return "\n".join(paragraphs)


def _normalize_newlines(text: str) -> str:
    """把 Windows / 旧 Mac 换行统一为 LF。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")
