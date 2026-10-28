"""基于字符的文本切分服务。

本模块只做字符级切分，不按 token 切分，也不调用任何模型或外部 API。
切分时优先寻找段落、换行、句子、逗号等语义边界；只有在超长文本没有任何
可用边界时，才退化为按 ``chunk_size`` 硬切，保证循环一定向前推进。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.exceptions import TextSplitError

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50

# 边界优先级从高到低：段落 > 换行 > 句子 > 逗号/顿号 > 空白。
# 对句子和逗号保留分隔符，让块末尾仍然是一个完整的语义单元。
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_LINE_BREAK = re.compile(r"\n")
_SENTENCE_END = re.compile(r"[。！？!?；;…]|\.(?=\s|$)")
_COMMA_BREAK = re.compile(r"[，,、]")
_WHITESPACE_BREAK = re.compile(r"\s+")

_BOUNDARY_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (_PARAGRAPH_BREAK, False),
    (_LINE_BREAK, False),
    (_SENTENCE_END, True),
    (_COMMA_BREAK, True),
    (_WHITESPACE_BREAK, False),
)


@dataclass(frozen=True, slots=True)
class TextChunk:
    """一个文本块及其在规范化源文本中的位置。

    ``start_index`` / ``end_index`` 使用 Python 字符下标（左闭右开），
    相对于去除首尾空白、统一换行符后的源文本。
    """

    chunk_index: int
    text: str
    start_index: int
    end_index: int

    @property
    def character_count(self) -> int:
        """文本块包含的字符数。"""
        return len(self.text)


def _validate_parameters(chunk_size: int, chunk_overlap: int) -> None:
    """校验切分参数，避免调用方传入负数、布尔值或无效组合。"""
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise TextSplitError(
            "chunk_size 必须是大于 0 的整数。",
            code="invalid_chunk_size",
            status_code=422,
        )
    if chunk_size <= 0:
        raise TextSplitError(
            "chunk_size 必须大于 0。",
            code="invalid_chunk_size",
            status_code=422,
        )

    if isinstance(chunk_overlap, bool) or not isinstance(chunk_overlap, int):
        raise TextSplitError(
            "chunk_overlap 必须是大于或等于 0 的整数。",
            code="invalid_chunk_overlap",
            status_code=422,
        )
    if chunk_overlap < 0:
        raise TextSplitError(
            "chunk_overlap 必须大于或等于 0。",
            code="invalid_chunk_overlap",
            status_code=422,
        )
    if chunk_overlap >= chunk_size:
        raise TextSplitError(
            "chunk_overlap 必须小于 chunk_size。",
            code="invalid_chunk_overlap",
            status_code=422,
        )


def _normalize_text(text: str) -> str:
    """统一换行符并去除首尾空白；空白文本直接报错。"""
    if not isinstance(text, str):
        raise TextSplitError(
            "text 必须是字符串。",
            code="invalid_text",
            status_code=422,
        )

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise TextSplitError(
            "text 不能为空或仅包含空白字符。",
            code="empty_text",
            status_code=400,
        )
    return normalized


def _find_boundary(window: str, min_offset: int) -> int | None:
    """在窗口内寻找最后一个不早于 ``min_offset`` 的语义边界。

    返回值的含义是“块结束位置”；句子和逗号边界会包含分隔符本身。
    找不到时返回 ``None``，由调用方按 ``chunk_size`` 硬切。
    """
    for pattern, include_separator in _BOUNDARY_PATTERNS:
        candidate: int | None = None
        for match in pattern.finditer(window):
            position = match.end() if include_separator else match.start()
            # 边界前的有效内容也要达到最小长度，避免在边界前只剩空白时
            # 产生一个极短的块（例如 "字\n" 被切成只剩 "字"）。
            content_before = window[:position].rstrip()
            if position >= min_offset and len(content_before) >= min_offset:
                candidate = position
        if candidate is not None and candidate > 0:
            return candidate
    return None


def split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """把非空文本切分为有序、可选重叠的字符块。

    Args:
        text: 待切分文本，不能为空或仅包含空白字符。
        chunk_size: 单块最大字符数，必须大于 0。
        chunk_overlap: 相邻块重叠字符数，必须满足
            ``0 <= chunk_overlap < chunk_size``。

    Returns:
        按原文顺序排列的文本块；``chunk_index`` 从 0 开始连续递增。

    Raises:
        TextSplitError: 文本为空或切分参数不合法。
    """
    _validate_parameters(chunk_size, chunk_overlap)
    source = _normalize_text(text)
    source_length = len(source)

    # 边界不能太靠近块开头，否则会产生大量极短的块。至少保留半个块，
    # 同时保证下一块能向前推进（重叠上限为 chunk_size - 1）。
    min_boundary_offset = max(1, chunk_size // 2, chunk_overlap + 1)
    chunks: list[TextChunk] = []
    start = 0

    while start < source_length:
        hard_end = min(start + chunk_size, source_length)

        if hard_end < source_length:
            boundary = _find_boundary(
                source[start:hard_end],
                min_offset=min_boundary_offset,
            )
            end = start + boundary if boundary is not None else hard_end
        else:
            end = hard_end

        # 防御性兜底：任何情况下都必须向前推进，避免无限循环。
        if end <= start:
            end = min(start + 1, source_length)

        raw_chunk = source[start:end]
        stripped_chunk = raw_chunk.strip()
        if stripped_chunk:
            # 去掉块首尾的空白后，位置元数据也同步收紧。
            left_trim = len(raw_chunk) - len(raw_chunk.lstrip())
            right_trim = len(raw_chunk) - len(raw_chunk.rstrip())
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    text=stripped_chunk,
                    start_index=start + left_trim,
                    end_index=end - right_trim,
                )
            )

        if end >= source_length:
            break

        # 下一块从当前块有效内容的末尾回退 overlap 个字符，保证重叠，
        # 同时跳过空白，避免新块以纯空白开头。
        content_end = end - (len(raw_chunk) - len(raw_chunk.rstrip()))
        next_start = content_end - chunk_overlap
        if next_start <= start:
            next_start = start + 1
        while next_start < source_length and source[next_start].isspace():
            next_start += 1
        if next_start <= start:
            next_start = start + 1
        if next_start >= source_length:
            break
        start = next_start

    return chunks


__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "TextChunk",
    "split_text",
]
