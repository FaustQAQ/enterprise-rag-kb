"""文档上传、解析、切分与持久化接口。"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import DocumentParseError
from app.schemas.document import (
    ChunkRequest,
    ChunkResponse,
    DocumentParseResponse,
    ErrorResponse,
    TextChunkResponse,
)
from app.schemas.document_embedding import DocumentEmbedResponse
from app.schemas.document_record import (
    DeleteDocumentResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummaryResponse,
)
from app.services.document_embedding import embed_document
from app.services.document_parser import (
    detect_file_type,
    normalize_filename,
    parse_document,
)
from app.services.document_store import (
    delete_document,
    get_document,
    list_documents,
    save_document,
)
from app.services.embedding_service import (
    EmbeddingNotConfiguredError,
    EmbeddingService,
    create_embedding_service,
)
from app.services.text_splitter import split_text

router = APIRouter(prefix="/documents", tags=["Documents"])

# 分块读取上传内容，避免一次性把未知大小的请求读进内存。
_READ_CHUNK_SIZE = 1024 * 1024


def _file_too_large_error(max_bytes: int) -> DocumentParseError:
    """构造包含配置上限的可读错误。"""
    limit_mb = max_bytes // (1024 * 1024)
    return DocumentParseError(
        f"文件大小超过限制，单个文件最大 {limit_mb} MB。",
        code="file_too_large",
        status_code=413,
    )


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传文件，超过限制时立即中止。

    同时利用 Starlette 已统计的 ``UploadFile.size`` 做快速拒绝，并在实际
    读取过程中逐块累加校验，避免“先读完全部内容再判断大小”。
    """
    if file.size is not None and file.size > max_bytes:
        raise _file_too_large_error(max_bytes)

    content = bytearray()
    while chunk := await file.read(_READ_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise _file_too_large_error(max_bytes)

    if not content:
        raise DocumentParseError(
            "文件内容为空，请上传非空文件。",
            code="empty_file",
            status_code=400,
        )

    return bytes(content)


def get_embedding_service(
    settings: Settings = Depends(get_settings),
) -> EmbeddingService | None:
    """返回已配置的 Embedding 服务；未配置时返回 None。

    工厂本身不发起网络请求。把“未配置”留给服务层在确认文档和文本块存在后
    处理，这样使用默认配置请求不存在的文档时仍然优先得到 404。测试可以通过
    ``app.dependency_overrides`` 注入 Mock 服务。
    """
    try:
        return create_embedding_service(settings)
    except EmbeddingNotConfiguredError:
        return None


@router.post(
    "/parse",
    response_model=DocumentParseResponse,
    summary="上传并解析文档",
    description=(
        "接收 multipart/form-data 文件，支持 .txt、.docx、.pdf，"
        "返回提取出的纯文本。文件不会被业务代码保存到项目磁盘。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "空文件或文件名无效"},
        413: {"model": ErrorResponse, "description": "文件超过大小限制"},
        415: {"model": ErrorResponse, "description": "不支持的文件格式"},
        422: {"model": ErrorResponse, "description": "文件编码或内容无法解析"},
    },
)
async def parse_document_file(
    file: UploadFile = File(
        ...,
        description="待解析文件，支持 .txt、.docx、.pdf，默认最大 10 MB",
    ),
    settings: Settings = Depends(get_settings),
) -> DocumentParseResponse:
    """校验上传文件并提取纯文本。"""
    # 先清洗文件名并校验扩展名，避免为不支持的格式读取文件内容。
    # 客户端提供的 Content-Type 不作为格式判断依据。
    filename = normalize_filename(file.filename)
    detect_file_type(filename)

    data = await _read_upload_limited(file, settings.max_upload_size_bytes)

    # PDF / DOCX 解析属于 CPU 密集型操作，放到线程池，避免阻塞事件循环。
    parsed = await run_in_threadpool(parse_document, filename, data)

    return DocumentParseResponse(
        filename=parsed.filename,
        file_type=parsed.file_type,
        character_count=parsed.character_count,
        text=parsed.text,
        message=f"解析成功，共提取 {parsed.character_count} 个字符。",
    )


@router.post(
    "/chunk",
    response_model=ChunkResponse,
    summary="按字符切分文本",
    description=(
        "把已经解析出的文本按字符切分为多个文本块。"
        "优先在段落、换行、句子和逗号处切分；本阶段不按 token 切分，"
        "也不生成 Embedding。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "文本为空或仅包含空白字符"},
        422: {"model": ErrorResponse, "description": "切分参数不合法"},
    },
)
def chunk_text(payload: ChunkRequest) -> ChunkResponse:
    """切分请求体中的文本，并返回有序的文本块及统计信息。"""
    chunks = split_text(
        payload.text,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )

    # 最后一个块的结束位置就是规范化源文本的总长度；块内部已去掉首尾空白。
    total_character_count = chunks[-1].end_index

    return ChunkResponse(
        chunks=[
            TextChunkResponse(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                character_count=chunk.character_count,
                start_index=chunk.start_index,
                end_index=chunk.end_index,
            )
            for chunk in chunks
        ],
        chunk_count=len(chunks),
        total_character_count=total_character_count,
    )


@router.post(
    "",
    response_model=DocumentDetailResponse,
    status_code=201,
    summary="上传文档并保存文本块",
    description=(
        "接收 multipart/form-data 文件，完成解析、按字符切分，"
        "然后在同一个数据库事务中保存文档和全部文本块。"
        "文件只在内存中处理，不会被永久保存。"
    ),
    responses={
        400: {"model": ErrorResponse, "description": "空文件、无效文件名或空文本"},
        409: {"model": ErrorResponse, "description": "文本块序号冲突"},
        413: {"model": ErrorResponse, "description": "文件超过大小限制"},
        415: {"model": ErrorResponse, "description": "不支持的文件格式"},
        422: {"model": ErrorResponse, "description": "文件内容或切分参数不合法"},
        500: {"model": ErrorResponse, "description": "数据库写入失败"},
        503: {"model": ErrorResponse, "description": "数据库暂时不可用"},
    },
)
async def create_document(
    file: UploadFile = File(
        ...,
        description="待入库文件，支持 .txt、.docx、.pdf，默认最大 10 MB",
    ),
    chunk_size: int = Form(
        default=500,
        gt=0,
        description="单块最大字符数",
    ),
    chunk_overlap: int = Form(
        default=50,
        ge=0,
        description="相邻块重叠字符数，必须小于 chunk_size",
    ),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetailResponse:
    """解析、切分并持久化一份文档。"""
    # 先校验文件名和格式，再读取内容，避免为非法请求消耗内存。
    filename = normalize_filename(file.filename)
    detect_file_type(filename)

    data = await _read_upload_limited(file, settings.max_upload_size_bytes)
    parsed = await run_in_threadpool(parse_document, filename, data)

    # 解析成功后一次性提交文档和文本块；失败时服务层会回滚整个事务。
    document = await save_document(
        db,
        filename=parsed.filename,
        file_type=parsed.file_type,
        text=parsed.text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return DocumentDetailResponse.model_validate(document)


@router.post(
    "/{document_id}/embed",
    response_model=DocumentEmbedResponse,
    summary="向量化指定文档",
    description=(
        "读取文档的全部文本块，调用已配置的 Embedding 服务生成真实向量，"
        "并在一个数据库事务中保存。未配置 Embedding 时返回明确错误，"
        "不会生成随机向量、全零向量或文本哈希。"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "文档或文本块不存在"},
        409: {"model": ErrorResponse, "description": "向量记录冲突"},
        422: {"model": ErrorResponse, "description": "文档没有文本块或输入非法"},
        500: {"model": ErrorResponse, "description": "向量保存或内部处理失败"},
        502: {"model": ErrorResponse, "description": "Embedding 服务返回异常数据或调用失败"},
        503: {"model": ErrorResponse, "description": "Embedding 未配置或数据库暂时不可用"},
        504: {"model": ErrorResponse, "description": "Embedding 服务请求超时"},
    },
)
async def embed_document_endpoint(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    service: EmbeddingService | None = Depends(get_embedding_service),
) -> DocumentEmbedResponse:
    """触发一份文档的完整向量化流程。"""
    result = await embed_document(db, document_id, service)
    return DocumentEmbedResponse(
        document_id=result.document_id,
        chunk_count=result.chunk_count,
        embedded_count=result.embedded_count,
        dimension=result.dimension,
        model=result.model,
        status=result.status,
        message=(
            f"文档向量化完成，共处理 {result.chunk_count} 个文本块，"
            f"向量维度为 {result.dimension}。"
        ),
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="查询文档列表",
    description="按创建顺序倒序分页返回文档摘要，不返回完整文本块正文。",
    responses={
        500: {"model": ErrorResponse, "description": "数据库查询失败"},
    },
)
async def get_document_list(
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="跳过的记录数"),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """分页查询文档摘要。"""
    documents, total = await list_documents(db, limit=limit, offset=offset)
    return DocumentListResponse(
        items=[
            DocumentSummaryResponse.model_validate(document)
            for document in documents
        ],
        total=total,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="查询文档详情",
    description="返回文档摘要及按 chunk_index 排序的全部文本块。",
    responses={
        404: {"model": ErrorResponse, "description": "文档不存在"},
        500: {"model": ErrorResponse, "description": "数据库查询失败"},
    },
)
async def get_document_detail(
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentDetailResponse:
    """查询单个文档及其文本块。"""
    document = await get_document(db, document_id)
    return DocumentDetailResponse.model_validate(document)


@router.delete(
    "/{document_id}",
    response_model=DeleteDocumentResponse,
    summary="删除文档",
    description="删除指定文档及其全部文本块和已保存向量，不会影响其他文档。",
    responses={
        404: {"model": ErrorResponse, "description": "文档不存在"},
        500: {"model": ErrorResponse, "description": "数据库删除失败"},
    },
)
async def remove_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> DeleteDocumentResponse:
    """删除文档、关联文本块和已保存向量。"""
    await delete_document(db, document_id)
    return DeleteDocumentResponse(
        document_id=document_id,
        message="文档、文本块及向量已删除。",
    )
