"""领域异常与统一错误响应。

文档上传 / 解析失败时抛出 DocumentParseError，文档入库、查询或删除失败时
抛出 DocumentPersistenceError，文本切分参数或输入不合法时抛出
TextSplitError，文档向量化或向量存储失败时抛出 DocumentEmbeddingError，
由应用级异常处理器转换成稳定的 JSON 结构。客户端只会看到错误码和可读提示，
不会看到内部堆栈、服务器路径或 API 密钥。
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DocumentParseError(Exception):
    """文档上传、校验或解析失败。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class DocumentPersistenceError(Exception):
    """文档入库、查询或删除失败（含 404 / 409 / 数据库错误）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class TextSplitError(ValueError):
    """文本切分参数或输入不合法。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class DocumentEmbeddingError(Exception):
    """文档向量化或向量存储失败。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class VectorStoreError(DocumentEmbeddingError):
    """向量仓储校验、查询或事务失败。

    继承 DocumentEmbeddingError，使 API 层可以用同一个异常处理器把仓储错误
    转换为统一 JSON；服务层直接调用时仍可按更具体的类型捕获。
    """


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """构造统一的错误响应体。"""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


async def document_parse_error_handler(
    _request: Request,
    exc: DocumentParseError,
) -> JSONResponse:
    """把文档领域异常转换为统一的 JSON 错误响应。"""
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def document_persistence_error_handler(
    _request: Request,
    exc: DocumentPersistenceError,
) -> JSONResponse:
    """把文档持久化异常转换为统一的 JSON 错误响应。"""
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def text_split_error_handler(
    _request: Request,
    exc: TextSplitError,
) -> JSONResponse:
    """把文本切分异常转换为统一的 JSON 错误响应。"""
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def document_embedding_error_handler(
    _request: Request,
    exc: DocumentEmbeddingError,
) -> JSONResponse:
    """把向量化 / 向量存储领域异常转换为统一 JSON 错误响应。"""
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def request_validation_error_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    """统一请求参数校验失败时的错误结构。

    FastAPI 默认返回 ``{"detail": [...]}``，与文档接口的错误格式不一致；
    这里转换为同样的 ``{"error": {...}}``，同时避免向前端暴露内部校验细节。
    """
    return build_error_response(
        status_code=422,
        code="validation_error",
        message="请求参数校验失败，请检查请求内容。",
    )
