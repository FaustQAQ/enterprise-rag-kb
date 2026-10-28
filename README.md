# Enterprise RAG Knowledge Base

Enterprise RAG Knowledge Base 是一个基于检索增强生成（RAG）的企业知识库应用，旨在帮助用户高效管理企业文档，并通过自然语言提问快速获取相关知识。系统支持文档上传、内容解析、文本分块、向量化存储、语义检索以及基于大语言模型的智能问答，并提供相关文档来源，提升回答的可追溯性。

项目采用 FastAPI 构建后端服务，使用 React、TypeScript 和 Vite 构建前端界面。支持本地 Mock 模式进行开发与演示，也支持接入兼容 OpenAI API 协议的 Embedding 和 LLM 服务，便于后续扩展与集成。

## 技术栈

| 层级 | 选型 |
| --- | --- |
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| 数据校验 | Pydantic 2.x + pydantic-settings |
| 文件上传 | python-multipart + FastAPI `UploadFile` |
| 文档解析 | pypdf（PDF）、python-docx（DOCX） |
| 文本切分 | 自研字符级切分（段落/换行/句子/逗号边界） |
| Embedding | 本地确定性 Mock Embedding + OpenAI 兼容 HTTP 适配器 |
| 数据持久化 | SQLAlchemy 2.x async，文档、文本块和向量分表持久化 |
| 向量存储 | `document_chunk_embeddings.vector` 保存 JSON 浮点数组，记录维度与模型名 |
| 数据库 | 默认 SQLite（本地开发）；生产可覆盖为 PostgreSQL，后续再迁移 pgvector |
| ORM | SQLAlchemy 2.x（async） |
| 数据库驱动 | aiosqlite（默认开发库与测试）、asyncpg（可选 PostgreSQL） |
| 大模型 | 默认开发使用 `MockLLMService`；配置完整且关闭 Mock 时使用 OpenAI 兼容真实 LLM，DeepSeek 隔离验证已有记录 |
| 测试 | pytest + FastAPI TestClient |
| 前端 | React + TypeScript + Vite（开发服务器默认 `http://localhost:5173`） |

## 目录结构

```text
enterprise-rag-kb/
├── .gitignore
├── README.md
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   ├── index.html
│   └── src/
└── backend/
    ├── .env.example
    ├── pytest.ini
    ├── requirements.txt
    ├── app/
    │   ├── main.py
    │   ├── api/
    │   ├── core/
    │   ├── models/
    │   ├── schemas/
    │   └── services/
    ├── scripts/
    │   └── init_db.py
    └── tests/
        ├── conftest.py
        ├── test_documents.py
        ├── test_document_embedding.py
        ├── test_retrieval_service.py
        ├── test_rag_service.py
        ├── test_chat_api.py
        ├── test_mock_embedding.py
        └── test_rag_e2e.py
```
分层约定：

- `api/`：只处理 HTTP 参数、依赖注入和响应封装。
- `services/`：文档解析、字符切分、文档持久化、向量校验与存储、向量化编排、Embedding 适配器等业务逻辑，不感知 multipart 请求。
- `schemas/`：Pydantic 请求 / 响应模型。
- `models/`：SQLAlchemy ORM 模型和表关系。
- `core/`：配置、数据库基础设施、统一异常。

## 环境要求

- Python 3.11+；本项目记录中已在 Python 3.13.17 的 `.venv-test-313` 环境验证后端测试。原 `.venv` 的可启动性需按本机实际情况检查，不应覆盖或重建已有环境。
- pip。
- 本地开发默认使用 SQLite，不需要安装或启动 PostgreSQL；数据库文件默认是 `backend/rag_kb.db`。
- PostgreSQL + pgvector 是后续生产部署方向；当前不要求安装，也没有使用 pgvector 的 `Vector` 列。
- 自动化测试不需要 PostgreSQL，测试夹具会为每个测试创建独立的临时 SQLite 文件，并在测试结束后清理。

## 本地安装与启动

以下命令在**项目根目录**执行。Windows 可使用 PowerShell 或 CMD。示例中的 %PROJECT_ROOT% 是占位变量，请先替换为本地项目根目录，或在当前终端定义该变量。

### 1. 选择并检查 Python 环境

项目已有 `.venv` 和 `.venv-test-313`，不要删除、覆盖或重建它们。项目记录中已验证 `.venv-test-313` 使用 Python 3.13.17；优先使用它：

```cmd
cd /d %PROJECT_ROOT%
.venv-test-313\Scripts\python.exe --version
call .venv-test-313\Scripts\activate.bat
python --version
python -c "import sys; print(sys.executable)"
```

本机如果没有可用的既有环境，才在一个全新的、未占用的路径创建虚拟环境；不要把示例命令用于覆盖现有 `.venv` 或 `.venv-test-313`。

PowerShell 激活命令为：

```powershell
cd %PROJECT_ROOT%
.\.venv-test-313\Scripts\Activate.ps1
```

macOS / Linux：

```bash
cd enterprise-rag-kb
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2. 安装依赖

```powershell
# 项目根目录，虚拟环境已激活
python -m pip install -r backend\requirements.txt
```

macOS / Linux：

```bash
python -m pip install -r backend/requirements.txt
```

### 3. 创建本地配置

```powershell
Copy-Item backend\.env.example backend\.env
```

macOS / Linux：

```bash
cp backend/.env.example backend/.env
```

`.env` 已被 `.gitignore` 忽略。不要提交真实 API Key；`.env.example` 中的 `LLM_API_KEY` 和 `EMBEDDING_API_KEY` 均为空。

### 4. 初始化数据库（使用持久化接口前）

默认配置使用 SQLite：

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./rag_kb.db
```

在 `backend` 目录执行建表脚本：

```powershell
cd backend
python -m scripts.init_db
```

脚本会创建 `documents`、`document_chunks`、`document_chunk_embeddings` 三张表。它只做 `CREATE TABLE`（已存在则跳过），不会删除已有表或数据，也不会自动修改旧表结构。

SQLite 数据库文件位于 `backend/rag_kb.db`，已被 `.gitignore` 忽略。如果已有旧版 SQLite 数据库，只需要重新执行一次 `python -m scripts.init_db`，就会补建新的向量表；旧文档和文本块数据不会被清空。当前没有引入 Alembic，因此旧表字段变更仍需要手动迁移。

也支持通过环境变量覆盖为 PostgreSQL：

```powershell
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/rag_kb"
python -m scripts.init_db
```

PostgreSQL 需要先创建数据库；当前表和检索逻辑只使用普通 JSON 字段，不要求安装 pgvector。后续迁移到 pgvector 时再增加扩展、`Vector` 列和索引。

> `/health`、`/parse`、`/chunk` 不访问数据库；文档入库、列表、详情、删除和向量化接口需要先执行初始化脚本。

### 5. 启动开发服务器

```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果 8000 端口已被占用，可以改用 `--port 8001`。

启动后可访问：

- 健康检查：http://127.0.0.1:8000/health
- Swagger UI：http://127.0.0.1:8000/docs
- ReDoc：http://127.0.0.1:8000/redoc
- OpenAPI JSON：http://127.0.0.1:8000/openapi.json

按 `Ctrl + C` 停止服务。

### Windows CMD 快速启动（Mock 演示）

使用已验证的 `.venv-test-313`；不要覆盖已有 `.venv` 或 `.venv-test-313`。如果依赖尚未安装，再在该环境中安装，并创建本地配置模板：

```cmd
cd /d %PROJECT_ROOT%
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
```

以下命令不会配置或调用真实模型 API；`set` 只对当前 CMD 窗口生效：

```cmd
cd /d %PROJECT_ROOT%
call .venv\Scripts\activate.bat
set ENVIRONMENT=development
set EMBEDDING_MOCK_ENABLED=true
cd /d %PROJECT_ROOT%\backend
python -m scripts.init_db
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`scripts.init_db` 只创建缺失表，但会写入默认的 `backend\rag_kb.db`；已有开发数据不会被清空。若数据库已经初始化，可跳过该命令。运行测试时使用：

```cmd
cd /d %PROJECT_ROOT%\backend
call ..\.venv-test-313\Scripts\activate.bat
python -m pytest -q -o addopts=
```

## 前端启动与联调

当前前端位于 `frontend/`，技术栈为 React + TypeScript + Vite。它没有配置 Vite 代理，`frontend/src/api.ts` 从 `VITE_API_BASE_URL` 读取后端地址；未设置时默认使用 `http://127.0.0.1:8000`。

Windows CMD 示例：

```cmd
cd /d %PROJECT_ROOT%\frontend
node --version
npm --version
if not exist package-lock.json echo ERROR: package-lock.json not found
if not exist node_modules npm ci
set VITE_API_BASE_URL=http://127.0.0.1:8000
npm run dev
```

Vite 默认打开 `http://localhost:5173`。另开终端可执行：

```cmd
cd /d %PROJECT_ROOT%\frontend
npm run lint
npm run build
```

`package-lock.json` 应与 `package.json` 一起保留；仅当依赖目录不存在或需要按锁文件恢复时使用 `npm ci`，不要把安装命令误认为本次已执行。后端启动和数据库初始化仍见上文；默认健康检查为 `http://127.0.0.1:8000/health`，Swagger 为 `http://127.0.0.1:8000/docs`。

浏览器 Chat 真实验收前，应先确认后端使用的是预期数据库、CORS 包含 `http://localhost:5173` 或 `http://127.0.0.1:5173`，并根据 `.env` 选择 Mock 或真实服务。构建通过不等于浏览器端到端通过。
## 接口说明

### RAG 问答接口

当前 B 方案已经提供以下本地闭环：

1. `POST /api/v1/documents`：上传、解析、切分并保存文档。
2. `POST /api/v1/documents/{document_id}/embed`：使用当前 Embedding 服务为文本块生成并保存向量。
3. `POST /api/v1/retrieval/search`：按模型、维度和余弦相似度检索文本块。
4. `POST /api/v1/chat`：检索知识库后调用 LLM 服务生成回答和来源；默认开发配置使用 `MockLLMService`，完整配置并关闭 Mock 后可选择真实 OpenAI 兼容 LLM。

当没有兼容的检索结果时，Chat 返回空 `sources` 和明确的无法根据知识库回答提示，不伪造知识库依据。当前默认 LLM 是 `MockLLMService`，不访问网络，也不需要 `LLM_API_KEY`。

Swagger UI、ReDoc、OpenAPI JSON 和健康检查地址分别为：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`
- `http://127.0.0.1:8000/openapi.json`
- `http://127.0.0.1:8000/health`

### `GET /health`

用于本地验收、容器探针和负载均衡健康检查。该接口不访问数据库或大模型。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期响应（HTTP 200）：

```json
{
  "status": "ok",
  "service": "Enterprise RAG Knowledge Base",
  "version": "0.1.0",
  "environment": "development"
}
```

### `POST /api/v1/documents/parse`

上传单个文档并提取纯文本。

- 请求格式：`multipart/form-data`，文件字段名为 `file`。
- 支持格式：`.txt`、`.docx`、`.pdf`，按**扩展名**判断，大小写不敏感。
- 客户端提供的 `Content-Type` 不作为格式判断依据。
- 默认大小上限：10 MiB，可通过 `MAX_UPLOAD_SIZE_MB` 调整（范围 1–100）。
- 文件不会被业务代码写入项目磁盘；Starlette 对大文件可能使用系统临时文件做缓冲，请求结束后自动清理。
- TXT 必须为 UTF-8（兼容 BOM）；PDF 暂不支持 OCR 和加密文档。

PowerShell（使用系统自带 `curl.exe`）：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/parse" `
  -F "file=@D:\path\to\handbook.txt"
```

macOS / Linux：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/parse" \
  -F "file=@./handbook.txt"
```

成功响应（HTTP 200）：

```json
{
  "filename": "handbook.txt",
  "file_type": "txt",
  "character_count": 9,
  "text": "企业知识库示例文本",
  "message": "解析成功，共提取 9 个字符。"
}
```

`character_count` 按 Unicode 码点计数，与返回的 `text` 长度一致。

统一错误响应格式：

```json
{
  "error": {
    "code": "file_too_large",
    "message": "文件大小超过限制，单个文件最大 10 MB。"
  }
}
```

主要错误码与状态码：

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 400 | `empty_file` | 文件为空或只有空白字符 |
| 400 | `missing_filename` / `invalid_filename` / `filename_too_long` | 文件名缺失、非法或过长 |
| 413 | `file_too_large` | 文件超过大小限制 |
| 415 | `unsupported_file_type` | 扩展名不是 `.pdf` / `.docx` / `.txt` |
| 422 | `invalid_text_encoding` | TXT 不是 UTF-8 编码 |
| 422 | `invalid_pdf` / `encrypted_pdf` | PDF 损坏、无法读取或已加密 |
| 422 | `pdf_no_extractable_text` | 扫描件或空白 PDF，暂不支持 OCR |
| 422 | `invalid_docx` / `docx_no_text` | DOCX 损坏或正文为空 |
| 422 | `validation_error` | 请求缺少 `file` 字段等参数错误 |

### `POST /api/v1/documents/chunk`

把已经解析出的文本按**字符**切分为有序文本块。该接口不调用大模型、不生成 Embedding，也不访问数据库。

请求体（JSON）：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 必填 | 待切分文本，不能为空或仅含空白字符 |
| `chunk_size` | integer | `500` | 单块最大字符数，必须大于 0 |
| `chunk_overlap` | integer | `50` | 相邻块重叠字符数，必须满足 `0 <= chunk_overlap < chunk_size` |

切分策略：

- 按字符数而不是 token 数切分。
- 优先在段落（空行）、换行、句子（`。！？!?；;…` 或英文句点）、逗号和空白处切分。
- 超长且没有可用边界的文本会按 `chunk_size` 硬切，保证一定向前推进。
- 每个块都带 `chunk_index`（从 0 开始）、`text`、`character_count`、`start_index`、`end_index`。
- `start_index` / `end_index` 是相对于**规范化文本**的字符下标：统一换行符并去掉首尾空白后的文本。

PowerShell：

```powershell
$body = @{
  text = "企业知识库问答。"
  chunk_size = 500
  chunk_overlap = 50
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/documents/chunk" `
  -ContentType "application/json" `
  -Body $body
```

macOS / Linux：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/chunk" \
  -H "Content-Type: application/json" \
  -d '{"text":"企业知识库问答。","chunk_size":500,"chunk_overlap":50}'
```

成功响应（HTTP 200）：

```json
{
  "chunks": [
    {
      "chunk_index": 0,
      "text": "企业知识库问答。",
      "character_count": 8,
      "start_index": 0,
      "end_index": 8
    }
  ],
  "chunk_count": 1,
  "total_character_count": 8
}
```

错误响应沿用统一格式：

```json
{
  "error": {
    "code": "empty_text",
    "message": "text 不能为空或仅包含空白字符。"
  }
}
```

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 400 | `empty_text` | `text` 为空或仅包含空白字符 |
| 422 | `validation_error` | 缺少字段，或 `chunk_size` / `chunk_overlap` 不合法 |

### `POST /api/v1/documents`

上传文档，完成解析、切分，并在**一个数据库事务**中保存文档和全部文本块。

- 请求格式：`multipart/form-data`。
- 必填文件字段：`file`。
- 可选字段：`chunk_size`（默认 500，必须大于 0）、`chunk_overlap`（默认 50，必须满足 `0 <= chunk_overlap < chunk_size`）。
- 支持格式、大小限制和解析错误规则与 `/parse` 完全一致。
- 文件只在内存中处理，不写入项目磁盘。
- 任一步骤失败都会回滚，不会留下“只有文档、没有文本块”的半条记录。

PowerShell：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents" `
  -F "file=@D:\path\to\handbook.txt" `
  -F "chunk_size=500" `
  -F "chunk_overlap=50"
```

macOS / Linux：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents" \
  -F "file=@./handbook.txt" \
  -F "chunk_size=500" \
  -F "chunk_overlap=50"
```

成功响应（HTTP 201，详情结构）：

```json
{
  "id": 1,
  "filename": "handbook.txt",
  "file_type": "txt",
  "character_count": 27,
  "status": "processed",
  "chunk_count": 2,
  "created_at": "2026-10-26T06:00:00Z",
  "updated_at": "2026-10-26T06:00:00Z",
  "chunks": [
    {
      "id": 1,
      "chunk_index": 0,
      "text": "企业知识库示例文本第一段。",
      "character_count": 13,
      "start_index": 0,
      "end_index": 13,
      "created_at": "2026-10-26T06:00:00Z"
    },
    {
      "id": 2,
      "chunk_index": 1,
      "text": "第二段示例。",
      "character_count": 6,
      "start_index": 13,
      "end_index": 19,
      "created_at": "2026-10-26T06:00:00Z"
    }
  ]
}
```

> 上例只展示结构，实际 `chunks` 数量由文本长度和切分参数决定。

### `GET /api/v1/documents`

分页查询文档摘要，不返回文本块正文。

| 查询参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | `20` | 每页数量，范围 1–100 |
| `offset` | integer | `0` | 跳过的记录数，必须大于等于 0 |

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/documents?limit=20&offset=0"
```

响应（HTTP 200）：

```json
{
  "items": [
    {
      "id": 1,
      "filename": "handbook.txt",
      "file_type": "txt",
      "character_count": 27,
      "status": "processed",
      "chunk_count": 2,
      "created_at": "2026-10-26T06:00:00Z",
      "updated_at": "2026-10-26T06:00:00Z"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/documents/{document_id}`

查询单个文档及按 `chunk_index` 升序排列的全部文本块。响应结构同上传入库接口的 201 响应。

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/documents/1"
```

文档不存在时返回 HTTP 404：

```json
{
  "error": {
    "code": "document_not_found",
    "message": "文档不存在。"
  }
}
```

### `DELETE /api/v1/documents/{document_id}`

删除指定文档及其全部文本块和已保存向量。删除语句严格限定该文档 ID，不会按文件名或其他条件误删其他文档。

```powershell
Invoke-RestMethod -Method Delete "http://127.0.0.1:8000/api/v1/documents/1"
```

成功响应（HTTP 200）：

```json
{
  "document_id": 1,
  "message": "文档、文本块及向量已删除。"
}
```

文档不存在时返回 HTTP 404，错误码为 `document_not_found`。

### `POST /api/v1/documents/{document_id}/embed`

触发指定文档的完整向量化流程。接口没有请求体，不接受客户端提交任意向量。

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/documents/1/embed"
```

成功响应（HTTP 200）：

```json
{
  "document_id": 1,
  "chunk_count": 2,
  "embedded_count": 2,
  "dimension": 1024,
  "model": "text-embedding-v4",
  "status": "completed",
  "message": "文档向量化完成，共处理 2 个文本块，向量维度为 1024。"
}
```

工作流程：

1. 按 `document_id` 查询文档和文本块；文档不存在返回 404。
2. 复制文本块 ID 与文本，结束读事务，避免在外部 HTTP 请求期间持有数据库事务。
3. 调用已配置的 `EmbeddingService`；真实适配器按批次请求供应商，Mock 服务在本地生成确定性向量。
4. 校验返回向量数量、顺序、类型、有限数值和维度。
5. 在一个事务中批量写入或更新 `document_chunk_embeddings`；任一步失败都不会报告成功。
6. 返回文档 ID、文本块总数、成功写入数量、向量维度、模型名和状态。

文档没有文本块时返回 422 `document_has_no_chunks`；Embedding 未配置时返回 503 `embedding_not_configured`。当前没有单独的“向量化状态查询”接口，文档详情的 `chunks` 也不返回完整向量，避免响应体过大和意外暴露向量数据。

向量化接口主要错误码：

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 404 | `document_not_found` / `chunk_not_found` | 文档或文本块不存在 |
| 409 | `vector_conflict` | 向量记录发生数据库冲突 |
| 422 | `document_has_no_chunks` | 文档没有可处理的文本块 |
| 422 | `invalid_embedding_input` | 文本块为空、文本块参数非法 |
| 502 | `embedding_provider_error` | 供应商 HTTP 错误或网络失败 |
| 502 | `invalid_embedding_response` | 返回数量、格式或维度不符 |
| 503 | `embedding_not_configured` | Mock 未显式启用且未配置真实 Embedding 服务 |
| 503 | `database_unavailable` | 数据库暂时不可用 |
| 504 | `embedding_timeout` | 调用供应商超时 |
| 500 | `invalid_embedding_dimension` / `invalid_stored_vector` | 维度或已存向量损坏 |
| 500 | `database_error` | 向量保存或查询失败 |

### 持久化接口的主要错误码

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 400 | `empty_file` | 上传文件为空或只有空白文本 |
| 404 | `document_not_found` | 查询或删除不存在的文档 |
| 409 | `document_conflict` | 文档保存时文本块序号冲突 |
| 413 | `file_too_large` | 文件超过 `MAX_UPLOAD_SIZE_MB` |
| 415 | `unsupported_file_type` | 扩展名不是 `.pdf` / `.docx` / `.txt` |
| 422 | `validation_error` | 缺少文件/参数，或表单字段类型不正确 |
| 422 | `invalid_chunk_overlap` | `chunk_overlap` 大于等于 `chunk_size` |
| 422 | `invalid_text_encoding` / `invalid_pdf` / `invalid_docx` 等 | 文件内容无法解析 |
| 500 | `database_error` | 数据库查询、写入或删除失败 |
| 503 | `database_unavailable` | 数据库连接暂时不可用 |

## Embedding 与向量化服务

`EmbeddingService` 负责“文本 → 向量”的外部调用，`vector_store` 负责向量校验与持久化，`document_embedding` 负责按文档编排两者。三层职责分离，向量存储不调用外部 API，Embedding 适配器也不直接操作数据库。

### 接口契约

```python
class EmbeddingService(ABC):
    @property
    def dimension(self) -> int: ...

    @property
    def model(self) -> str | None: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
```

- `embed_documents` 返回数量、顺序与输入完全一致；空列表直接返回 `[]`，不创建 HTTP 请求。
- `embed_query` 与 `embed_documents` 使用同一个模型、同一向量空间和维度。
- 空字符串、只含空白的字符串、非字符串输入会抛出 `EmbeddingInputError`。
- Mock 关闭且真实 provider / API Key / model / dimension 未完整配置时，工厂抛出 `EmbeddingNotConfiguredError`；显式开启 Mock 时才使用本地特征哈希，Mock 结果不代表真实语义 Embedding。
- 外部服务失败、超时、非 JSON、数量或维度不符分别映射为 `EmbeddingProviderError`、`EmbeddingTimeoutError`、`EmbeddingResponseError`。
- `model` 只有真实适配器才知道；未实现该属性的测试替身默认返回 `None`，不会伪造模型名。

### 文档向量化编排

`embed_document` 的实际顺序：

1. 查询文档和文本块；不存在返回 404。
2. 复制文本块 ID、文本和文档 ID，结束当前读事务。
3. 在事务外调用 `EmbeddingService.embed_documents`。
4. 校验数量、顺序、每一条向量的长度、有限数值和配置维度。
5. 在单个数据库事务中批量更新或插入向量；失败全部回滚。
6. 返回 `DocumentEmbeddingResult`，不把未完成的批次报告为成功。

这样既避免数据库事务跨越外部 HTTP 请求，也保证“生成失败”与“保存失败”都不会留下部分成功的结果。

### 创建与调用

```python
import asyncio
from app.services.embedding_service import create_embedding_service

async def main() -> None:
    service = create_embedding_service()  # 从环境变量 / backend/.env 读取配置
    vectors = await service.embed_documents(["第一段", "第二段"])
    query_vector = await service.embed_query("查询文本")
    print(service.dimension, len(vectors), len(query_vector))

asyncio.run(main())
```

`create_embedding_service` 本身不发起网络请求；只有调用 `embed_documents` / `embed_query` 时才访问外部服务。未配置时会在创建阶段直接给出配置错误。

### OpenAI 兼容协议

当前适配器向以下地址发送请求：

```http
POST {EMBEDDING_BASE_URL}/embeddings
Authorization: Bearer <EMBEDDING_API_KEY>
Content-Type: application/json

{"model": "<EMBEDDING_MODEL>", "input": ["文本 1", "文本 2"]}
```

- 请求会按 `EMBEDDING_BATCH_SIZE` 自动分批，结果按全局输入顺序拼接。
- 使用 `EMBEDDING_TIMEOUT_SECONDS` 控制连接、读取等超时。
- 响应要求包含 `data[].embedding`；若供应商提供 `data[].index`，服务按它恢复顺序，未提供时按响应位置处理，并校验数量、索引完整性和每条向量的维度。
- 向量必须是有限数值，NaN、无穷大、字符串和布尔值都会被拒绝。
- 错误信息不会包含 API Key；请求头和完整正文不会写入日志。

### Embedding 配置

```dotenv
ENVIRONMENT=development
EMBEDDING_MOCK_ENABLED=false
EMBEDDING_PROVIDER=
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
EMBEDDING_TIMEOUT_SECONDS=30
EMBEDDING_BATCH_SIZE=10
```

支持的 `EMBEDDING_PROVIDER`：`openai`、`openai_compatible`、`openai-compatible`。只有 provider 非空，且 API Key、模型、维度均已配置时，工厂才会创建真实适配器。

本地 B 方案演示可在 development 环境显式设置 `EMBEDDING_MOCK_ENABLED=true`。Mock Embedding 使用本地确定性特征哈希，不访问网络、不需要 API Key，也不具备真实语义模型的检索质量。production 环境禁止启用 Mock。真实 Embedding 适配器已使用百炼中国大陆兼容接口完成单文本验证，并完成隔离环境的 HTTP 上传—解析—分块—向量化—持久化—检索验证；这不等同于生产验收。

> 自动化测试使用 `httpx2.MockTransport` 等离线替身，不访问网络；另有独立的真实 API 诊断记录。真实请求是否成功仍取决于本地密钥、网络、供应商权限、限流和模型配置，不能仅由配置项存在推断。

## 数据库表结构

### `documents`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer PK | 自增主键 |
| `filename` | varchar(255) | 清洗后的文件名 |
| `file_type` | varchar(16) | `pdf` / `docx` / `txt` |
| `character_count` | integer | 解析文本的字符数，检查约束 `>= 1` |
| `status` | varchar(32) | 处理状态，本阶段固定为 `processed` |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

### `document_chunks`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer PK | 自增主键 |
| `document_id` | integer FK | 关联 `documents.id`，`ON DELETE CASCADE`，有索引 |
| `chunk_index` | integer | 文档内从 0 开始的序号 |
| `text` | text | 文本块内容，不能为空 |
| `character_count` | integer | 文本块字符数，检查约束 `>= 1` |
| `start_index` | integer | 规范化原文起始下标，检查约束 `>= 0` |
| `end_index` | integer | 规范化原文结束下标，检查约束 `> start_index` |
| `created_at` | timestamptz | 创建时间 |

### `document_chunk_embeddings`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | integer PK / FK | 关联 `document_chunks.id`，`ON DELETE CASCADE`，一个文本块最多一条向量 |
| `vector` | JSON | 浮点数数组，按文本块保存当前 Embedding 服务结果 |
| `dimension` | integer | 向量长度，检查约束 `> 0`，必须与向量实际长度一致 |
| `model` | varchar(255) | 生成该向量的模型标识；Mock 或未知时按实现记录 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

关系与约束：

- 一份 `Document` 对应多个 `DocumentChunk`；每个 `DocumentChunk` 最多对应一条 `DocumentChunkEmbedding`。
- `document_chunk_embeddings` 使用 `chunk_id` 作为主键，天然保证一个文本块只有一条向量。
- `UNIQUE(document_id, chunk_index)` 保证同一文档内文本块序号不重复。
- 删除文档时，服务层在同一事务中先删除该文档的向量，再删除文本块，最后删除文档；SQLite 默认不强制外键，因此不依赖数据库级联。
- `vector` 是普通 JSON 数组，不与某个 Embedding 供应商绑定；`dimension` 和 `model` 用于校验和追踪。当前没有创建 pgvector `Vector` 列，也没有相似度索引。
- 可保存真实适配器或显式启用的本地 Mock 向量；未配置服务或调用失败时不会写入伪造向量。

现有数据库兼容方式：

- 本阶段只新增 `document_chunk_embeddings` 表，不修改 `documents` / `document_chunks` 的已有字段。
- 对已有 SQLite 数据库，重新执行 `python -m scripts.init_db` 即可补建新表；`create_all` 不会删除或重建已有表。
- 当前没有引入 Alembic。若将来修改旧表字段，需要单独的迁移方案，不能依赖 `create_all`。

实际存储位置：

- 默认开发配置使用 SQLite，数据库文件为 `backend/rag_kb.db`（相对 `backend` 启动目录），已被 `.gitignore` 忽略。
- 通过 `DATABASE_URL` 可覆盖为 PostgreSQL；此时数据位于 PostgreSQL 服务端数据目录，数据库名由连接串决定。
- 自动化测试使用 pytest 临时目录下的独立 SQLite 文件，每个测试结束自动清理，不污染开发库。

## 运行测试

```powershell
cd backend
pytest -v
```

预期结果：

```text
已有验收记录（本次文档修正未重新运行测试）：

- 端到端测试：8 passed
- 专项回归测试：154 passed
- 全量后端测试：历史记录中曾有 265 passed，另有普通 Windows CMD 记录为 303 passed in 23.17s。两者对应的代码版本、执行轮次或测试范围差异无法仅由当前文件确认；本项目本轮未重新运行全量测试，不能将任一数字表述为当前结果。
```

测试使用内存中的文本和文件，不依赖真实企业文档、PostgreSQL、pgvector、网络、大模型 API Key 或 Embedding API Key；数据库相关测试使用 pytest 临时目录中的独立 SQLite 文件。覆盖：

- 健康检查、OpenAPI 路由。
- 有效 TXT（含中文、BOM）、DOCX、PDF。
- 空文件、不支持格式、扩展名优先于 Content-Type。
- 缺少文件字段、超过大小限制。
- 损坏 PDF、扫描件 PDF、非 UTF-8 TXT。
- 路径穿越文件名清洗。
- 文本切分：空文本、短文本、长文本、中文、重叠、段落/句子边界、无边界超长文本、空白块过滤、稳定输出、非法参数。
- Chunk API 的成功响应、空文本错误、参数错误和 OpenAPI 注册。
- 文档入库：多文本块关联、列表、详情、404。
- 删除文档时只删除目标文档的文本块。
- 事务提交失败时回滚，不产生不完整记录。
- 同一文档内 `chunk_index` 唯一约束。
- 空文件、非法切分参数、不支持格式不入库。
- Embedding 抽象接口契约、配置工厂和未配置时的明确错误。
- Embedding Mock 调用：批量顺序、分批、请求头/请求体、query 调用。
- Embedding 输入校验：空文本、空白文本、非字符串、空列表。
- Embedding 外部异常转换：HTTP 错误、网络错误、超时、非 JSON、数量/维度/索引/数值格式异常。
- Embedding 错误信息不泄露 API Key，所有测试不访问外部服务。
- 向量保存、读取、更新、批量写入和重复 `chunk_id` 校验。
- NaN、Infinity、布尔值、字符串、空向量和维度不符的拒绝。
- 向量批量保存提交失败时回滚，不留下部分向量。
- 文档向量化 API 的正常流程、404、无文本块、未配置服务、供应商失败、超时、返回数量/维度异常。
- 删除文档后向量被清理，不产生孤立数据。
- OpenAPI 文档包含 `/api/v1/documents/{document_id}/embed`。

## 配置项

配置文件为 `backend/.env`，模板为 `backend/.env.example`。字段名大小写不敏感。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `APP_NAME` | `Enterprise RAG Knowledge Base` | OpenAPI 文档中的服务名，也用于健康检查响应 |
| `APP_VERSION` | `0.1.0` | 服务版本 |
| `ENVIRONMENT` | `development` | 运行环境：`development` / `testing` / `production` |
| `DEBUG` | `false` | 是否开启 FastAPI 调试模式；同时控制 SQL echo |
| `API_V1_PREFIX` | `/api/v1` | 业务 API 的统一前缀 |
| `MAX_UPLOAD_SIZE_MB` | `10` | 单个上传文件的最大大小（MiB），允许 1–100 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./rag_kb.db` | SQLAlchemy 异步连接串；可覆盖为 PostgreSQL，测试夹具会覆盖为临时 SQLite |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许跨域的前端来源，英文逗号分隔 |
| `LLM_API_KEY` | 空 | 在线大模型密钥，后续阶段使用；禁止提交真实值 |
| `LLM_BASE_URL` | 空（模板示例为 `https://api.openai.com/v1`） | 在线大模型 API 地址（按实际供应商修改） |
| `LLM_MODEL` | 空（模板示例为 `gpt-4.1-mini`） | 在线大模型名称（按实际供应商修改） |
| `EMBEDDING_PROVIDER` | 空 | Embedding 提供商：`openai` / `openai_compatible` / `openai-compatible`；为空表示未启用 |
| `EMBEDDING_API_KEY` | 空 | Embedding API 密钥，只允许来自环境变量或 `.env`；禁止提交真实值 |
| `EMBEDDING_BASE_URL` | 模板为百炼兼容地址 | OpenAI 兼容 API 根地址，服务负责规范化并追加 `/embeddings` |
| `EMBEDDING_MODEL` | 模板示例为 `text-embedding-v4` | Embedding 模型名称 |
| `EMBEDDING_DIMENSION` | 模板示例为 `1024` | 预期向量维度；用于校验供应商响应，必须与模型实际维度一致 |
| `EMBEDDING_TIMEOUT_SECONDS` | `30` | 单次 HTTP 请求超时时间（秒），必须大于 0 且不超过 300 |
| `EMBEDDING_BATCH_SIZE` | `10` | 单次请求最多发送的文本数；`text-embedding-v4` 按供应商限制最多 10 条，服务自动分批 |

## 依赖说明

完整版本与注释见 `backend/requirements.txt`，作用概览：

| 依赖 | 作用 |
| --- | --- |
| `fastapi` | HTTP 路由、依赖注入、请求校验、OpenAPI 文档 |
| `uvicorn[standard]` | ASGI 服务器，提供本地开发与热重载能力 |
| `pydantic` | 请求 / 响应模型校验与序列化 |
| `pydantic-settings` | 从环境变量和 `.env` 加载配置 |
| `python-dotenv` | 解析 `.env` 文件 |
| `python-multipart` | 解析 multipart/form-data 文件上传 |
| `pypdf` | 纯 Python 读取 PDF 并逐页提取文本 |
| `python-docx` | 读取 DOCX 段落正文 |
| `SQLAlchemy[asyncio]` | 2.x ORM 与异步数据库访问 |
| `aiosqlite` | SQLite 异步驱动，默认开发数据库和测试使用 |
| `asyncpg` | 可选 PostgreSQL 异步驱动；默认 SQLite 路径不加载 |
| `pgvector` | 预留依赖：后续迁移 PostgreSQL 向量列时使用；当前不创建 `Vector` 列 |
| `pytest` | 测试框架 |
| `httpx2` | Embedding 在线适配器的异步 HTTP 客户端，同时作为 Starlette `TestClient` 后端；本项目未额外引入旧版 `httpx` |

## 当前阶段边界

已实现：

- FastAPI 应用工厂与应用入口。
- pydantic-settings 配置模块（支持 `.env`，密钥不落代码）。
- SQLAlchemy 2.x 异步引擎、会话工厂和声明式 `Base`。
- 根路径 `/health` 健康检查。
- `POST /api/v1/documents/parse`：TXT / DOCX / PDF 上传与文本提取。
- 上传大小限制、扩展名校验、文件名清洗、统一错误响应。
- `POST /api/v1/documents/chunk`：按字符切分文本，支持 `chunk_size` / `chunk_overlap`，优先语义边界。
- `Document` / `DocumentChunk` / `DocumentChunkEmbedding` ORM 模型，含外键、唯一约束、检查约束和索引。
- `POST /api/v1/documents`：解析、切分并在单事务中保存文档和文本块。
- `GET /api/v1/documents`、`GET /api/v1/documents/{id}`、`DELETE /api/v1/documents/{id}`：列表、详情和级联删除。
- 默认 SQLite 开发数据库、初始化脚本和独立临时 SQLite 测试库。
- `EmbeddingService` 抽象接口与 OpenAI 兼容 HTTP 适配器。
- Embedding 配置工厂、输入校验、批量请求、超时控制和响应维度/格式校验；Mock 显式开启时使用本地确定性特征哈希，关闭且未配置真实服务时返回明确错误。
- `MockEmbeddingService`：development/testing 中显式启用，用于离线开发、测试和演示；不具备真实语义检索质量。
- `document_chunk_embeddings` 向量表：JSON 浮点数组、维度、模型名、时间戳，以及文本块向量的一对一关系。
- `vector_store` 服务：向量的保存、更新、读取、存在性检查、批量事务和非法向量校验。
- `document_embedding` 编排服务：事务外调用 Embedding、校验返回值、事务内批量保存、失败不报告成功。
- `POST /api/v1/documents/{document_id}/embed`：触发指定文档的向量化，返回块数、成功数、维度、模型和状态。
- `POST /api/v1/retrieval/search`：按兼容模型、维度和余弦相似度检索文本块。
- `ChatRequest`、`ChatSource`、`ChatResponse` Schema 与 `rag_service` RAG 编排。
- `LLMService` / `MockLLMService` 和 `POST /api/v1/chat`；空上下文时明确拒答并返回空来源。
- 删除文档时显式清理关联文本块和向量，避免 SQLite 外键未启用时产生孤立数据。
- Embedding 服务全部通过 Mock 测试，不依赖真实 API Key 或网络。
- v1 路由聚合，后续业务统一挂在 `/api/v1`。
- CORS 配置，支持当前 React + Vite 前端开发地址。
- pytest 接口与单元测试。
- `.env.example`、`.gitignore`、依赖清单和运行文档。

明确未实现或未完成（不等同于本地 Mock 验收）：

- 生产环境的 Embedding/LLM 验收、并发稳定性、限流重试和质量评测；真实服务的隔离环境验证已有记录，但不等同于生产验收。
- 向量索引、关键词检索和重排。
- PostgreSQL + pgvector 的 `Vector` 列、HNSW / IVFFlat 索引和生产迁移。
- 完整文本清洗与去重。
- 对话历史、Prompt 编排、流式回答。
- 用户认证、权限、租户隔离。
- 数据库迁移工具（当前只用 `scripts/init_db.py` 建表）。
- OCR、加密 PDF、旧版 `.doc` 支持。
- 浏览器真实 Chat 完整端到端验收；当前已有用户截图证明知识检索和 Chat 页面展示场景完成，但截图不能证明该次请求重新调用了真实 Embedding 或 DeepSeek。

## 已知限制

- 默认开发库是 SQLite；它适合本地开发和测试，不适合多实例并发生产部署。切换 PostgreSQL 时通过 `DATABASE_URL` 覆盖即可，但需要自行创建数据库并执行 `python -m scripts.init_db`。
- 向量以 JSON 数组保存在 `document_chunk_embeddings.vector`，不是 pgvector 原生类型，也没有相似度索引；当前 Python 余弦检索适合本地小规模演示，不适合生产规模。
- 当前没有 Alembic 迁移；修改已有表结构时需要手动迁移。新增向量表可由 `create_all` 补齐，但不要依赖它修改旧列。
- `POST /api/v1/documents/{id}/embed` 在请求内同步调用外部 Embedding 服务，大文档可能耗时较长；后续应改为后台任务，并增加任务状态和幂等控制。
- 上传内容只在内存中处理，服务重启后不会保留未入库的临时文件；入库后的数据保存在 SQLite 或 PostgreSQL。
- `status` 目前固定为 `processed`，尚未实现异步处理状态流转。
- 自动化测试不访问真实供应商；真实百炼与 DeepSeek 的单请求及隔离环境验证来自独立诊断记录，仍需浏览器、生产安全和稳定性验收。
- 没有认证与权限控制，删除和向量化接口不应直接暴露到公网。
- 当前没有完整文本清洗/去重、关键词检索/重排、对话历史和流式回答能力；本地 Mock RAG 与 Chat API 已实现。

## 下一步建议

1. 在隔离环境之外继续验证真实模型的限流、重试、错误码和质量边界；不要把真实密钥提交到仓库。
2. 引入 Alembic 管理现有表结构，并准备 PostgreSQL + pgvector 迁移：给文本块增加 `Vector` 列和 HNSW / IVFFlat 索引。
3. 在现有向量保存接口之上增加相似度检索，先完成单文档最小检索闭环，再加入关键词检索和重排。
4. 把文档向量化改为后台任务，增加任务状态、重试和幂等控制，避免大文档长时间占用 HTTP 请求。
5. 增加异步集成测试与本地 docker-compose（PostgreSQL + pgvector）。
6. 完成可追溯的浏览器真实 Chat 完整链路验收，并补充认证授权、迁移、异步任务、并发和质量评测。
