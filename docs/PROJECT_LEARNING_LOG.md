# Enterprise RAG Knowledge Base 开发记录与学习复盘

> 本文是持续维护的开发日志。“已确认”有当前代码、测试输出或用户提供的历史记录支持；“历史记录”不等于本次重新执行；“待验证”不作事实结论。

## 记录规则

- 项目当前包含 backend 和 frontend；后端是 FastAPI，前端实际代码是 React + TypeScript + Vite。
- 后端测试位于 backend/tests，当前可见 19 个 test_*.py 文件。
- 配置由 backend/app/core/config.py 的 Settings 从环境变量和 backend/.env 读取。本日志不读取或记录 .env 秘密值。
- README 中的命令是操作说明，不代表本次执行过。
- 历史测试数量若来自用户或之前的终端记录，明确标为历史记录。

## 一、按时间顺序的开发记录

### 1. 项目骨架、配置和数据库

目标：建立 FastAPI 应用、配置加载、异步数据库会话、SQLAlchemy 模型和统一错误响应。

证据文件：

- backend/app/main.py
- backend/app/core/config.py
- backend/app/core/database.py
- backend/app/core/exceptions.py
- backend/app/models/base.py
- backend/app/models/document.py
- backend/scripts/init_db.py
- backend/requirements.txt

已确认事实：

- 配置使用 pydantic-settings，默认环境为 development。
- 默认数据库为 sqlite+aiosqlite:///./rag_kb.db；从 backend 启动时对应 backend/rag_kb.db。
- 模型包含 documents、document_chunks 和 document_chunk_embeddings。
- 文档块以 document_id 与 chunk_index 唯一；向量记录以 chunk_id 为主键，因此一个文本块最多一条向量记录。
- scripts.init_db 使用建表逻辑，不是完整迁移工具。

项目命令（来自 README，未在本次文档任务中重跑）：

~~~cmd
cd /d .
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
cd /d .\backend
python -m scripts.init_db
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

需要理解的专业知识：

- FastAPI 应用工厂、依赖注入和 ASGI 启动。
- SQLAlchemy 2.x 异步会话、事务、外键级联和唯一约束。
- SQLite 适合本地开发，但不等于生产级并发数据库；建表也不等于迁移。

### 2. 文档解析、文本切分和持久化

目标：支持 TXT、DOCX、PDF 解析，按字符和语义边界切分，并在一个事务中保存文档与文本块。

涉及文件：

- backend/app/services/document_parser.py
- backend/app/services/text_splitter.py
- backend/app/services/document_store.py
- backend/app/api/v1/documents.py
- backend/tests/test_documents.py
- backend/tests/test_document_persistence.py
- backend/tests/test_text_splitter.py

已确认事实：

- 存在 parse、chunk、上传入库、列表、详情、删除和向量化接口。
- 上传流程是解析、切分、保存文档和全部文本块。
- 入库失败不会留下只有文档没有文本块的半条记录。
- 删除按文档 ID 删除文档、文本块和关联向量。

需要理解的专业知识：

- multipart/form-data、扩展名校验和文件大小限制。
- 字符切分与 token 切分的差异。
- 事务提交、回滚和级联删除如何保护一致性。

### 3. 问答 Schema

目标：定义请求、来源和响应的稳定数据契约。

涉及文件：

- backend/app/schemas/chat.py
- backend/tests/test_chat_schemas.py

已确认事实：

- ChatRequest 清理问题首尾空白并校验 top_k、document_id、min_score。
- ChatSource 保存分块、文档、正文和分数，不返回原始向量或认证信息。
- ChatResponse 支持空 sources。
- 历史记录：用户报告该阶段新增 Schema 测试为 35 passed；本日志不把它当作本次重新执行结果。

需要理解的专业知识：

- Pydantic 2 的 model_validate、model_dump 和字段校验。
- 严格整数校验与 Python 中 bool 属于 int 子类的差异。
- API Schema 是外部契约，不应直接暴露 ORM 或供应商响应。

### 4. LLM 抽象与 Mock LLM

目标：在不调用真实模型的前提下，建立可替换的 LLM 接口和确定性 Mock。

涉及文件：

- backend/app/services/llm_service.py
- backend/app/api/v1/chat.py
- backend/tests/test_llm_service.py
- backend/tests/test_llm_integration.py
- backend/tests/test_llm_factory.py

已确认事实：

- LLMService.generate_answer(question, contexts) 是异步抽象接口，返回答案字符串。
- MockLLMService 不联网，基于传入上下文生成明确标记为 Mock 的答案。
- 上下文为空时返回明确拒答。
- LLMServiceError 用于输入、网络、超时和非法响应等错误映射。
- 历史记录：用户报告 LLM 新增测试 20 passed、Chat/RAG 相关测试 40 passed、全量 285 passed；这些是历史记录。

需要理解的专业知识：

- 抽象接口与依赖注入如何隔离业务编排和模型供应商。
- Mock 必须可预测且明确标记，不能伪装成真实模型输出。
- 供应商错误不能把密钥、响应体或堆栈返回给客户端。

### 5. Embedding、向量存储和检索

目标：实现 Embedding 接口、向量校验、持久化、模型/维度隔离和余弦相似度检索。

涉及文件：

- backend/app/services/embedding_service.py
- backend/app/services/document_embedding.py
- backend/app/services/vector_store.py
- backend/app/services/retrieval.py
- backend/app/models/document.py
- backend/app/api/v1/retrieval.py
- backend/tests/test_embedding_service.py
- backend/tests/test_embedding_integration.py
- backend/tests/test_vector_store.py
- backend/tests/test_document_embedding.py
- backend/tests/test_retrieval_service.py
- backend/tests/test_retrieval_api.py

已确认事实：

- Mock Embedding 使用本地确定性特征哈希，不访问网络、不读取 API Key、不使用随机向量。
- 向量保存为 JSON 浮点数组，同时保存 model 和 dimension。
- 检索按维度和模型标识过滤，再计算 Python 余弦相似度。
- 文档向量化在外部调用完成并校验后，事务内批量保存；失败保护旧向量。
- text-embedding-v4 适配逻辑包含可配置 dimensions、每请求最多 10 条文本和响应向量校验。
- 历史记录：Mock Embedding 阶段全量曾达到 251 passed；后续端到端 8 passed、专项回归 154 passed、全量 257 passed。这些不是本次文档任务重跑结果。

需要理解的专业知识：

- 向量空间必须保持模型和维度一致，不能跨模型直接比较。
- 余弦相似度只有在向量空间兼容时有意义；Mock 分数不能解释为真实语义相关性。
- 批量、超时、限流、响应数量和维度校验是供应商适配器的核心边界。

## 二、证据分类（阶段一）

以上内容来自当前目录结构、README、配置、模型、服务和测试文件；测试数字来自用户/历史终端记录，未在本次任务重新执行。

### 6. RAG 编排和 Chat API

目标：把请求校验、检索、LLM 调用和来源组装串成 HTTP 问答闭环。

涉及文件：backend/app/services/rag_service.py、backend/app/api/v1/chat.py、backend/app/api/v1/router.py、backend/app/schemas/chat.py、backend/tests/test_rag_service.py、backend/tests/test_chat_api.py、backend/tests/test_rag_e2e.py。

已确认事实：

- POST /api/v1/chat 依赖数据库、Embedding 服务和 LLM 服务。
- 没有检索结果时仍调用 Mock LLM，返回明确拒答和空来源。
- 来源保留 chunk_id、document_id、chunk_index、文件名、正文和分数。
- min_score 会传入检索服务并影响来源。
- 端到端测试覆盖上传、向量化、检索和 Chat 来源一致性。
- 历史记录：用户报告 test_rag_e2e.py 为 8 passed，全量为 265 passed。

需要理解的专业知识：RAG 通过检索上下文约束答案并提供可追溯来源；空结果拒答是降低幻觉风险的业务规则；422、502、503 等状态码应对应不同错误类别。

### 7. 异步测试辅助函数修复

历史问题：两个 RAG 测试把已经执行完成的 ChatResponse 再传入 asyncio.run，导致 ValueError: a coroutine was expected。

排查结论：

- 检查了 test_rag_service.py 的 _run、_answer 和 rag_service.py 的异步接口契约。
- 根因是测试辅助函数和调用方式不一致，不是 RAG 业务接口需要改成同步。
- 修复方向是调整测试辅助函数/调用方式，同时保留真实异步检索和 LLM 调用。

需要理解的专业知识：async def 返回 coroutine；asyncio.run 只能接收尚未运行的 coroutine；测试辅助函数应明确返回 coroutine 还是已解析结果。

### 8. 真实服务适配器的离线协议阶段

目标：为未来真实服务保留 OpenAI 兼容适配器，但不进行线上联调。

涉及文件：backend/app/services/embedding_service.py、backend/app/services/llm_service.py、backend/app/core/config.py、backend/.env.example、backend/tests/test_bailian_embedding.py、backend/tests/test_llm_integration.py、backend/tests/test_llm_factory.py。

已确认事实：

- 配置包含 Mock 开关、provider、API Key、base URL、model、timeout、dimension 和 batch size。
- production 环境禁止通过配置错误静默回退到 Mock。
- 测试使用 MockTransport 或测试替身，不调用真实供应商 API。
- 历史记录：用户报告 DeepSeek LLM 代码完成、20 passed、全量 285 passed；这不等于真实 API 联调成功。

需要理解的专业知识：OpenAI 兼容只说明协议相似，不代表模型名称、维度、限流和供应商行为已验证；测试 transport 能验证请求体、认证头和错误映射；生产配置失败时必须 fail closed。

### 9. React 前端 API 联调

目标：保留工作台视觉结构，将文档、检索和 Chat 页面接入真实后端 API。

涉及文件：frontend/src/api.ts、frontend/src/App.tsx、frontend/src/App.css；检查但未改动 frontend/src/index.css；CORS 检查 backend/app/core/config.py。

已确认事实：

- 前端 API 层支持健康检查、文档列表、上传、向量化、检索和 Chat。
- 默认后端地址为 http://127.0.0.1:8000，支持 VITE_API_BASE_URL 覆盖。
- 后端默认 CORS 包含 localhost:5173 和 127.0.0.1:5173，因此本轮没有修改后端。
- 本次前端修改后的 npm run lint 和 npm run build 实际通过。
- 检查时 127.0.0.1:8000 不可访问，未完成运行时 HTTP 联调。

需要理解的专业知识：API 层集中处理请求和错误；CORS 是浏览器安全策略；页面统计只能使用后端真实字段。

### 10. Markdown 展示和重复来源

目标：让 Chat 回答可读，并避免同一 chunk_id 在前端重复展示。

已确认事实：

- 当前使用安全的 React 元素渲染 Markdown 子集：标题、粗体、无序/有序列表和换行；没有使用 dangerouslySetInnerHTML。
- 曾尝试安装 react-markdown 和 remark-gfm，但当前环境安装过程未完成，未把依赖写入 package.json。
- 前端按稳定 chunk_id 去重；不同 chunk_id 即使文本相同也会保留。
- 后端模型中 DocumentChunkEmbedding.chunk_id 是主键，RAG 代码按命中一对一组装来源；重复现象的运行时来源因后端未启动仍待验证。
- 本次修改后的前端 npm run lint、npm run build 实际通过。
- 后端 pytest 未能在本次环境运行：虚拟环境启动器在中文路径下无法创建进程。没有因此修改测试或业务代码。

需要理解的专业知识：React 的 key 不是去重机制；去重应使用稳定业务标识；模型输出必须按文本解析，不能直接执行原始 HTML。

## 三、当前证据分类

### 已确认

- 后端存在文档、文本切分、向量化、检索、RAG 和 Chat API。
- Mock Embedding 和 Mock LLM 代码存在，并设计为离线使用。
- SQLite 向量表保存向量、模型和维度；chunk_id 是向量主键。
- React 前端存在统一 API 层，最近一次 lint/build 实际通过。

### 历史记录

- 35、204、223、237、251、257、265、285 passed 等数字来自之前项目交互或用户终端记录，本文件不声称本次重跑。
- DeepSeek、百炼 Embedding 的离线协议测试通过不等于真实供应商 API 已联调。

### 待验证

- 真实 Embedding 与真实 DeepSeek API 的线上协议、维度、限流、计费和超时。
- 当前数据库是否存在重复来源，以及运行中 Chat 返回的 source 数组。
- 服务启动后的完整浏览器流程。
- README 中 Vue 3 描述与当前 React 前端的最终统一。

## 四、后续维护格式

每次开发任务后追加日期/阶段、目标、实际修改文件、实际命令与结果、已验证事实、未解决问题、专业知识和下一步。不要用计划替代执行记录。

## 五、本次排查：重复检索、Chat 来源和 Markdown

### 数据库只读检查

执行了只读 SQLite 查询，数据库文件为 backend/rag_kb.db；没有修改、删除或重建数据。为了避免输出知识正文，查询结果只记录元数据和正文 SHA-256 前缀。

实际事实：数据库有 4 个文档和 4 个文本块。文档 2、3、4 的文件名、块序号和正文哈希相同；文档 3、4 的向量模型均为 text-embedding-v4、维度均为 1024、向量 JSON 长度相同。文档 2 使用 local-mock-embedding-v1、1536 维，因此会被当前 text-embedding-v4 查询的模型/维度过滤掉。

结论：截图中文档 3 和 4 的重复来自重复上传形成的两个独立文档记录，不是同一 chunk_id 被数据库重复保存，也不是 React key 导致的单纯重复渲染。此前数据库模型已经保证一个 chunk_id 最多一条向量记录；当前上传接口没有已确认的去重契约，因此本次不删除现有文档。

### 最小修复

修改 backend/app/services/retrieval.py：检索结果只在文件名、chunk_index、正文、model 和 dimension 五项全部一致时合并重复知识块。不同文件名、不同分块、不同模型或不同维度仍保留。Chat 使用同一检索结果，因此 Chat sources 同步去重；frontend/src/App.tsx 原有的 chunk_id 防御性去重仍保留。

新增测试：backend/tests/test_retrieval_service.py 验证相同文件名和正文的重复文档只保留一条，同时不同文件名仍保留；backend/tests/test_chat_api.py 验证 Chat sources 和传给 LLM 的 contexts 同步去重。

### Markdown 检查

frontend/src/App.tsx 使用 React 元素渲染标题、粗体、无序/有序列表和换行，frontend/src/App.css 提供样式；不使用 dangerouslySetInnerHTML，因此原始 HTML 不会执行。不同 Markdown 功能的浏览器运行时显示尚未在本次环境手工打开页面确认，标记为待验证。

### 本次实际命令和结果

- 在 frontend 目录执行 npm run lint：通过。
- 在 frontend 目录执行 npm run build：通过，TypeScript 和 Vite 构建通过。
- 使用可用的 Python 3.11 解释器对三个修改后的 Python 文件执行 AST 解析：通过。
- 尝试在 backend 目录执行 tests/test_retrieval_service.py 和 tests/test_chat_api.py 的 pytest：未执行成功。项目 .venv Python 启动器在中文路径下无法创建进程，退出码 101；这不是断言失败，也没有修改测试来规避。
- 没有调用真实 Embedding 或 LLM API，没有执行数据库写入。

### 需要理解的专业知识

- 相同正文只能作为重复判断的一部分；文件名、块序号、模型和维度共同限制去重范围。
- 数据库唯一约束防止同一实体重复，不会阻止用户重复上传形成多个文档实体。
- 依赖注入测试和实际 HTTP/数据库联调是不同层次的证据，不能互相替代。

### 待调查

- 现有重复文档 2、3、4 是否应由产品规则合并或由用户通过删除接口清理，未执行破坏性操作。
- Python 虚拟环境启动器在中文路径下的运行环境问题需要单独修复后，才能获得本次后端测试的真实通过数。
- Markdown 在真实浏览器中的视觉效果和复杂 Markdown 语法仍待手工验收。

## 六、后端测试环境复查

本次按用户要求优先检查测试环境，没有修改前端、检索业务逻辑或数据库。

### 检查结果

- .venv/pyvenv.cfg 显示 Python 3.13.14，home 和 executable 指向 Microsoft Store 的 Python 3.13 路径。
- .venv/Scripts/python.exe、pytest.exe 和 py.test.exe 文件存在；backend/pytest.ini 使用 tests、pythonpath=. 和默认 addopts=-q。
- backend/requirements.txt 声明 pytest 9.1.1、FastAPI、Pydantic 2.14.1、SQLAlchemy、aiosqlite 等依赖。

### 实际测试命令和错误分类

在 backend 目录执行：

~~~powershell
..\.venv\Scripts\python.exe -m pytest tests\test_retrieval_service.py tests\test_chat_api.py -q -o addopts=
..\.venv\Scripts\pytest.exe tests\test_retrieval_service.py tests\test_chat_api.py -q -o addopts=
~~~

两条命令均未进入 pytest 收集或断言阶段，退出码为 101。错误是启动错误：Unable to create process，错误文本中的中文项目路径被显示为问号，指向 venv 启动器无法访问其 pyvenv.cfg 中的 Microsoft Store Python。

为区分依赖错误，使用可用的 Python 3.11 解释器并把 venv site-packages 放入 PYTHONPATH 后尝试同一测试命令。pytest 9.1.1 可以导入，但收集 conftest.py 时失败：pydantic_core._pydantic_core 缺少 ArgsKwargs。这是依赖 ABI 错误，原因是 venv 中的 CPython 3.13 扩展不能由 Python 3.11 加载；该次退出码为 4，也没有执行测试。

结论：本次没有测试断言失败，也没有发现数据库问题；没有可报告的实际通过数量。静态 AST 检查和前端构建不能替代后端 pytest。

### 需要理解的专业知识

- Windows venv 的 python.exe 仍依赖 pyvenv.cfg 指定的基础解释器；基础解释器不可访问时，pytest 不会启动。
- CPython 原生扩展带有 Python ABI/版本约束；不能用 Python 3.11 运行面向 3.13 构建的 pydantic_core。
- 进程启动错误、依赖导入错误、pytest 收集错误、断言失败和数据库错误必须分开记录。

### 待解决方案

- 在不重建本项目现有环境的前提下，需要提供一个可访问的 Python 3.13 基础解释器，或由用户确认后在 ASCII 路径重新创建同版本隔离环境并按 requirements.txt 安装。
- 本次没有重建虚拟环境，也没有安装/升级依赖；因此后端测试结果仍待环境修复后重新确认。

## 七、独立测试环境任务复查

本次任务要求非破坏性建立独立 Python 3.13 测试环境。实际检查结果如下：

- 项目根目录、backend 目录以及三份持续维护文档均存在。
- py 命令和 Python Launcher 不可用；where python 只找到 Microsoft Store 的 WindowsApps 别名。
- python3.13.exe、WindowsApps 中的 PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\python.exe 和 python3.13.exe 均无法实际启动。PowerShell 报告进程无法正常运行/标准错误编码问题，不能仅凭文件存在认定解释器可用。
- 没有找到可访问的独立 CPython 3.13 安装路径。由于没有可用 Python 3.13，本次没有创建 D:\\venvs\\enterprise-rag-kb；D:\\venvs 原本也不存在。
- 没有安装依赖，没有修改现有 .venv，没有覆盖任何已有目录。
- 没有 Git 仓库元数据可供检查；git status 返回 not a git repository。未执行任何 reset、clean 或提交操作。

测试隔离检查：backend/tests/conftest.py 使用 pytest 的 tmp_path，为每个测试创建独立的 test_rag.db，并通过 app.dependency_overrides 覆盖 get_db；目标检索和 Chat 测试使用 Fake Embedding、Fake LLM 和临时数据库，不会修改 backend/rag_kb.db，也不访问真实模型 API。

本次没有运行目标 pytest，因为最高前置条件“可实际启动的 Python 3.13”未满足。没有测试通过、失败或跳过数量可报告；这不是断言失败。

需要理解的专业知识：Windows Store Python 别名和真正解释器不同；虚拟环境必须由可访问的基础解释器创建；测试夹具的临时数据库隔离与解释器环境是两个独立问题；不能用 Python 3.11 加载面向 3.13 的原生依赖来替代测试。

下一步阻塞：需要一个可实际启动的 CPython 3.13 及其完整路径。确认后再在不存在的英文路径创建新环境、按现有 requirements.txt 安装，并重新运行两个目标测试。

## 八、Python 3.13 独立测试环境修复

本次使用用户提供的 CPython 3.13.17，路径为 Python 3.13.17 的用户环境解释器路径。由于创建 外部独立环境目录 返回 WinError 5，为避免修改原有 .venv，在项目目录创建了独立环境 ./.venv-test-313。

虚拟环境初始化时系统默认临时目录不可写，临时将 TEMP/TMP 指向项目内 .tmp-python 后完成 ensurepip。随后按现有 backend/requirements.txt 安装依赖成功，python -m pip check 返回 No broken requirements found。

首次运行目标测试因 pytest 默认临时目录不可写得到 16 passed, 51 errors，错误均发生在 tmp_path 创建阶段。将本进程 TEMP/TMP 指向项目临时目录后重新执行：

~~~powershell
cd /d ./backend
./.venv-test-313/Scripts/python.exe -m pytest tests/test_retrieval_service.py tests/test_chat_api.py -q -o addopts=
~~~

结果为 67 passed：检索服务 50 passed，Chat API 17 passed，失败 0，跳过 0。测试夹具仍使用 tmp_path/test_rag.db 和 app.dependency_overrides[get_db]，没有写入 backend/rag_kb.db。

需要理解的专业知识：虚拟环境的 Python 版本和原生依赖 ABI 必须一致；pip check 不能替代 pytest；pytest 的 tmp_path 依赖系统临时目录；应区分环境错误与业务断言失败。

当前仍待处理：由于 外部独立环境目录 受系统权限限制，独立环境实际位于项目内 .venv-test-313；原 .venv 未修改。本次尚未执行全量 pytest。
## 九、后端全量 pytest 执行记录

在执行前复核了 backend/pytest.ini 和 backend/tests/conftest.py。pytest 配置仅指定 tests 目录和 pythonpath；公共夹具通过 pytest 的 tmp_path 创建每个测试独立的 test_rag.db，并覆盖 get_db 依赖。未发现目标测试直接使用 backend/rag_kb.db。

本次创建并验证可写的临时目录：./.tmp-pytest-full-20261028，并仅用于当前测试进程的 TEMP/TMP。

实际命令：

~~~powershell
cd /d ./backend
./.venv-test-313/Scripts/python.exe -m pytest tests -q -o addopts=
~~~

实际运行时设置了 TEMP/TMP 为上述临时目录。全量测试进程在本轮等待期间被中断，未产生最终 pytest 汇总行和可靠的通过、失败、跳过数量；因此本次不能报告全量测试通过，也不能据此判断业务回归。只读检查显示中断后没有可见的 python/pytest 进程。此前有效的目标测试记录 67 passed 仍然保留，不能替代全量测试。

需要理解的专业知识：长时间无输出不等于测试通过；全量 pytest 必须以最终汇总和退出码为证据；中断执行只能记录为未完成，不能推断失败原因或通过数量。

当前待处理：在不修改代码和数据库的前提下，重新执行全量 pytest，并保留完整最终输出、退出码和失败分类。
## 十、全量测试停滞定位

本次先使用独立解释器确认环境：

- Python 3.13.17
- sys.executable 为项目内 .venv-test-313 的 Scripts/python.exe
- pip check：No broken requirements found

pytest.ini、tests/conftest.py 和测试代码复核结果：

- pytest 配置使用 tests 目录，未配置网络测试插件。
- conftest.py 通过 tmp_path 创建 test_rag.db，并覆盖 get_db。
- 测试中出现的 HTTP 客户端均使用 MockTransport、Fake 服务或依赖覆盖；未发现真实 Embedding、LLM 或数据库 API 调用。
- 应用默认数据库连接虽然配置为 backend/rag_kb.db，但数据库引擎是惰性创建，数据库相关测试使用覆盖后的临时会话。

外部临时目录 不存在，但当前环境拒绝创建该目录。未清空或覆盖该位置。复用上一轮已验证可写的项目临时目录：

./.tmp-pytest-full-20261028

收集命令：

~~~powershell
cd /d ./backend
./.venv-test-313/Scripts/python.exe -m pytest tests --collect-only -q -o addopts=
~~~

收集成功，退出码 0，共收集 303 项测试。

全量详细运行使用：

~~~powershell
./.venv-test-313/Scripts/python.exe -m pytest tests -vv -s -o addopts=
~~~

当前进程设置 TEMP/TMP 为上述可写临时目录，并设置 180 秒诊断上限。运行实际开始于第一个测试：

tests/test_bailian_embedding.py::test_v4_request_contains_dimensions_and_no_duplicate_embeddings_path

180 秒内没有进入测试体完成或断言阶段，最后输出停留在该测试名称。诊断包装器退出码为 124，并只终止本次启动的 pytest 进程；没有获得 pytest 自身的最终汇总，因此全量 passed、failed、skipped 数量均未知。

单独重跑该测试时，使用 faulthandler_timeout=10，错误堆栈停在测试第 63 行的 asyncio.run，具体位于 Windows asyncio 创建事件循环时的 socket.py accept、_fallback_socketpair 和 windows_events.py。测试尚未执行 OpenAI 兼容服务请求、MockTransport handler 或任何断言。

进一步使用当前进程的 WindowsSelectorEventLoopPolicy 重跑，仍在 asyncio.run 创建事件循环时停滞；独立的 asyncio.run(asyncio.sleep(0)) 最小脚本也在 15 秒诊断上限内超时。该证据将问题收敛到当前 Windows 执行环境的 asyncio socketpair/accept 初始化阻塞，而不是供应商网络、真实 API、数据库隔离或 Embedding 响应逻辑。

本次没有修改业务代码、测试代码、依赖或数据库；此前 67 项目标测试通过记录保持不变。

需要理解的专业知识：pytest collection 成功只说明模块可导入和测试可发现；事件循环初始化可以在测试体第一行阻塞；MockTransport 不能消除 asyncio 事件循环自身的系统依赖；超时包装器的退出码不等于 pytest 失败汇总。

下一步：在允许 Windows 本地 socketpair 正常工作的终端或主机上复用同一 .venv-test-313 重跑；验收标准是获得 pytest 最终汇总和退出码，再判断是否存在业务测试失败。
## 十一、替代测试环境检查

本次仅做环境探测，没有安装软件、创建 Linux 环境或修改项目。

WSL 检查：

~~~powershell
wsl.exe --status
wsl.exe --list --quiet
~~~

两条命令均返回退出码 -1，并出现 Wsl/E_ACCESSDENIED；未能访问可运行的 Linux 发行版。因此没有继续执行 /mnt/d 访问、Linux venv 或 Linux pytest。

Docker 检查：

~~~powershell
docker.exe version
~~~

Docker CLI 可执行，报告客户端版本信息，但连接 Docker Desktop Linux daemon 失败，提示 named pipe 不存在；退出码为 1。没有启动或安装 Docker。

Python Launcher 检查：

~~~powershell
py.exe -0p
py.exe -3.13 -c "import sys; print(sys.version); print(sys.executable)"
~~~

Launcher 报告 No installed Pythons found；py -3.13 返回退出码 112。没有发现其他可由 Launcher 管理的 Python 3.13。

对已知两个 Python 3.13 解释器分别运行 10 秒上限的 asyncio 最小脚本：

- Python 3.13.17 的用户环境解释器路径：版本 3.13.17，路径正确，但 asyncio.run(asyncio.sleep(0)) 超时。
- ./.venv-test-313/Scripts/python.exe：版本 3.13.17，路径正确，但同一 asyncio 最小脚本超时。

本次未找到可正常运行 asyncio 的替代环境，因此没有创建 Linux 测试环境，也没有执行 Linux collect-only 或全量 pytest。此前 Windows collect-only 的 303 项收集记录和 67 项目标测试通过记录保持不变；不能将它们改写为全量测试通过。

需要理解的专业知识：Python 解释器能启动不代表 Windows asyncio 事件循环可用；WSL CLI 存在不代表发行版可访问；Docker CLI 存在不代表 daemon 正在运行；替代环境检查必须记录命令和退出码。

下一步：需要用户提供可访问的 WSL 发行版、修复当前 Windows 的 asyncio socketpair 权限/策略，或确认使用另一台可运行 Python 3.13 的 Windows/Linux 主机。获得可用环境后，再创建独立测试环境并执行 303 项全量测试。
## 十二、Windows asyncio 初始化阻塞的进一步诊断

本次对两个解释器分别执行了独立 10 秒子进程探针：

- Python 3.13.17 的用户环境解释器路径
- ./.venv-test-313/Scripts/python.exe

文件存在性：两者均为 True。

基础启动和隔离启动：

- 基础 Python 探针输出 python-start-ok，退出码 0。
- -I -S 隔离启动输出解释器路径、Python 3.13.17 和 isolated-start-ok，退出码 0。
- 正常模式 asyncio.run(asyncio.sleep(0))：10 秒超时。
- -I -S 隔离模式 asyncio.run(asyncio.sleep(0))：10 秒超时。
- 两种解释器的结果一致。

socket 和事件循环探针：

- socket.socketpair() 输出 socket-before 后 10 秒超时。
- 默认 WindowsProactorEventLoopPolicy 下 asyncio.new_event_loop() 输出 loop-before 后 10 秒超时。
- WindowsSelectorEventLoopPolicy 在当前解释器可用，但 asyncio.new_event_loop() 同样输出 loop-before 后 10 秒超时。
- faulthandler 调用栈显示 socket.socketpair 的 Windows fallback 停在 socket.py 的 accept；事件循环初始化进一步停在 proactor_events.py 或 selector_events.py 调用同一 fallback 的路径。

本地 TCP 对照探针：

~~~python
server.bind(("127.0.0.1", 0))
server.listen(1)
client.connect(server.getsockname())
~~~

结果：bind/listen 成功，但 client.connect 立即返回 WinError 10013，提示以不允许的方式访问套接字。该结果解释了 socketpair fallback 的 accept 停滞，也解释了 asyncio 事件循环自管道初始化无法完成。

配置检查：

- PYTHONHOME、PYTHONPATH、PYTHONASYNCIODEBUG 均未设置。
- sitecustomize.py 和 usercustomize.py 未在实际 sys.path 中发现。
- 两个解释器的标准库路径均正常指向 Python 3.13.17 安装目录；虚拟环境 base_prefix 正确指向该安装。
- TEMP/TMP 可被当前进程设置为项目临时目录；socket 诊断在该设置下仍复现。
- 没有修改注册表、系统策略、全局 Python 配置或项目代码。

结论：根因已从“未知 asyncio 阻塞”收敛为当前执行环境对本地 TCP socket connect 的权限拒绝，WinError 10013 是直接证据。尚不能仅凭现有证据区分 Windows 防火墙、终端安全软件、应用容器/沙箱或其他网络策略。全量 pytest 仍无法完成；全量通过、失败、跳过数量未知。

需要理解的专业知识：事件循环初始化可能依赖本地 socketpair；socket bind/listen 成功不代表 connect 权限允许；-I -S 能排除 Python 环境变量和 site 初始化干扰，但不能绕过操作系统 socket 权限；WinError 10013 需要由系统安全策略管理员进一步确认。

下一步：在允许当前 Python 进程进行本地 loopback socket connect 的终端或主机上重跑 asyncio 探针，再执行 303 项全量 pytest。不要通过修改业务代码绕过事件循环。
## 十三、本地回环、端口范围和防火墙只读检查

本次所有网络探针均使用独立 Python 子进程；socket 操作设置 2 秒超时，探针进程设置 15 秒上限。未修改系统配置。

### IPv4 和 IPv6 回环阶段

探针记录了 socket、bind、listen、connect、accept 各阶段：

- IPv4 127.0.0.1：socket、bind、listen 成功；connect 立即失败。
- IPv4 connect 异常：PermissionError，errno=13，WinError=10013。
- IPv4 因 connect 失败未进入 accept 阶段。
- IPv6 ::1：socket、bind、listen 成功；connect 立即失败。
- IPv6 connect 异常：PermissionError，errno=13，WinError=10013。
- IPv6 因 connect 失败未进入 accept 阶段。
- 探针进程整体退出码 0，表示探针已完成记录，不代表回环连接成功。

名称解析：

- localhost 同时解析为 127.0.0.1 和 ::1。
- 127.0.0.1 解析为 IPv4 回环。
- ::1 解析为 IPv6 回环。

因此当前不是单一 IPv4 或 IPv6 地址解析问题；两个回环协议的 connect 都被拒绝。

### TCP 排除端口范围

执行：

~~~powershell
netsh interface ipv4 show excludedportrange protocol=tcp
netsh interface ipv6 show excludedportrange protocol=tcp
~~~

两条命令均返回退出码 1，当前 netsh 运行环境提示 command not found，未能读取排除范围。没有证据证明存在端口排除范围冲突，也没有权限或依据修改任何范围。

### Windows Defender Firewall 和日志

只读执行 Get-NetFirewallProfile、Get-NetFirewallRule，以及：

~~~powershell
netsh advfirewall show allprofiles
~~~

结果：

- Get-NetFirewallProfile 和 Get-NetFirewallRule 均因无法从客户端访问 CIM 资源而失败。
- netsh advfirewall 命令在当前运行环境中同样提示 command not found，退出码 1。
- 默认日志路径 Windows 防火墙默认日志路径 不存在。
- 日志目录 Windows 防火墙默认日志目录 不存在。

因此本次无法确认防火墙配置、阻止规则或日志事件；不能据此断言是 Defender Firewall。

### 受管控运行环境证据

当前 PowerShell 进程路径位于 Codex runtime；环境中可观察到：

- CODEX_PERMISSION_PROFILE=:workspace
- CODEX_SANDBOX_NETWORK_DISABLED=1
- CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY 已设置
- TEMP/TMP 位于 受限执行环境的用户临时目录
- 当前进程为受管控 Codex 沙箱中的 PowerShell

这些是当前执行环境受沙箱管控的直接证据，但不能单独证明具体哪个系统组件拒绝了 loopback connect。结合 IPv4/IPv6 都返回 WinError 10013、Windows 防火墙查询不可访问、WSL/Docker 不可用，当前最保守结论是：受管控执行环境阻止了本地 TCP connect；具体责任组件仍待管理员或非沙箱终端确认。

全量 pytest 仍未完成，没有最终汇总。此前 303 项收集和 67 项目标测试通过记录保持不变。

需要理解的专业知识：bind/listen 成功与 connect 权限是不同阶段；IPv4/IPv6 对照可排除单协议问题；端口排除范围与 socket 权限拒绝不是同一类证据；防火墙配置不可访问时不能把“未查到规则”写成“没有规则”。

下一步：在普通非沙箱 Windows 终端或管理员可访问的诊断环境中，仅复跑本地 IPv4/IPv6 connect 探针和 netsh/Get-NetFirewallProfile，再决定是否需要系统管理员处理。
## 十四、普通 Windows CMD 中完成后端全量测试

根据用户提供的普通 Windows CMD 实际执行日志，补记本次已完成的验收事实。此前 Codex 受管控执行环境中，asyncio.run(asyncio.sleep(0)) 和本地 loopback TCP 曾出现阻塞或 WinError 10013；用户随后在普通 Windows CMD 中运行独立探针，结果分别为 ASYNCIO_OK 和 LOOPBACK_OK。

随后在 backend 目录使用独立测试环境执行：

~~~cmd
"..\.venv-test-313\Scripts\python.exe" -m pytest tests -vv -s -o addopts=
~~~

执行环境和结果：

- Python：3.13.17
- pytest：9.1.1
- pytest 配置：backend/pytest.ini
- 测试目录：backend/tests
- 收集测试数：303
- 最终结果：303 passed in 23.17s
- failed：0
- skipped：0
- pytest 正常输出完整最终汇总并正常结束。

这次结果说明：项目测试代码、测试夹具和当前独立依赖环境可以在普通 Windows CMD 中完成全量自动化测试；此前未完成是因为运行环境不同，当前证据支持普通 CMD 与此前受管控执行环境在本地 asyncio/loopback 能力上存在行为差异。仅凭本次成功结果，不能确定此前具体由防火墙、终端安全软件、沙箱策略或其他系统组件造成。

测试覆盖了文档解析、文本切分、文档持久化、向量存储、Mock/协议 Embedding、相似度检索、RAG 编排、Chat API、LLM 服务与工厂、API Schema、健康检查及端到端隔离测试。测试夹具仍使用临时 SQLite 数据库，没有把通过结果建立在真实项目数据库写入上。

### 需要理解的专业知识

- pytest collection 只证明测试可发现；最终汇总和正常退出才是完整执行证据。
- conftest.py 中的临时数据库和依赖覆盖可以让数据库测试与开发数据库隔离。
- Mock Embedding、Mock LLM 和 MockTransport 验证的是本地协议、编排和错误处理，不等于真实供应商 API 联调。
- asyncio 事件循环初始化可能依赖本地 loopback socket；不同终端或受管控环境可能产生不同系统行为。
- 全量自动化测试通过不等于浏览器端到端、真实模型 API 或生产部署通过。

仍待验证：真实 Embedding/LLM 供应商联调、浏览器完整流程、生产部署能力和安全工程化能力。此前关于受限环境的历史记录保留为诊断记录，不改写为项目代码失败。
## 十五、真实百炼 Embedding API 最小验证（2026-10-28）

本次按“只发送一次单文本请求”的范围执行真实 Embedding 验证。使用项目现有配置加载机制读取 Embedding 配置，并调用 `create_embedding_service()`。凭证状态仅记录为“已配置”，没有输出密钥、长度、前后缀或请求头。工厂实际创建的服务类型为 `OpenAICompatibleEmbeddingService`，没有启用 MockTransport、Fake 服务或测试依赖覆盖。

实际调用的是服务的单文本 `embed_query()`，输入为 `Enterprise RAG embedding connectivity test.`。请求没有写入数据库、上传文档或调用 LLM，也没有重试或切换到 Mock。请求在真实 HTTP 传输阶段失败，底层错误为 `httpx2.ConnectError`，由项目适配器转换为脱敏的 `EmbeddingProviderError`。未收到百炼 HTTP 状态码或响应体，因此无法验证真实返回模型、1024 维度或有限数值。此次不是模型响应格式错误，也不能据此判定 API 凭证无效；当前失败阶段是网络连接建立阶段。

本次没有修改业务代码、测试代码、依赖、数据库或虚拟环境。真实 Embedding 最小验证仍未完成，不能把本次真实请求失败写成供应商联调成功。此前 303 项离线全量测试记录保持不变；离线测试通过不等于真实 API 验证通过。

### 需要理解的专业知识

- 配置项存在只说明应用能够读取配置，不能证明 API Key 有效、账户有权限或网络链路可用。
- `create_embedding_service()` 只创建适配器；真正的外部请求发生在 `embed_query()` 或 `embed_documents()`。
- `ConnectError` 表示连接建立阶段失败，和供应商返回 401、429、500 或非法 JSON 是不同的故障类别。
- 只有取得真实 HTTP 响应并校验模型、向量维度及有限数值后，才能把最小真实 API 验证标记为完成。
- MockTransport 协议测试可以验证请求构造和异常处理，但不能替代真实网络、认证和供应商服务验证。

下一步：在允许访问百炼地址的普通非沙箱终端中，使用相同配置再次执行一次单文本验证；仅在获得真实成功响应后，才继续隔离测试数据库中的文档向量化和检索闭环。
## 十六、普通 CMD 可复现脚本准备与第二次真实请求（2026-10-28）

根据普通 Windows CMD 的 `curl.exe -I` 结果，百炼 HTTPS 地址能够返回 `401 Unauthorized`，说明该终端具备基础网络可达性，但该结果不等于 Embedding API 请求认证成功。

本次在当前 Codex 运行环境中再次执行了严格的一次真实请求。使用 `.venv-test-313`、项目配置和 `create_embedding_service()` 创建 `OpenAICompatibleEmbeddingService`；输出确认 `transport_injected=False`。仅调用一次 `embed_query("Enterprise RAG embedding connectivity test.")`，没有重试、写库、上传文档或调用 LLM。

结果：请求约 5.3 秒后失败，异常类型为脱敏后的 `EmbeddingProviderError`，没有获得 HTTP 状态码或供应商响应。当前证据表明本次环境仍未完成到百炼的有效 HTTP 请求，但不能把它与普通 CMD 的 401 连通性结果混为一谈；两者运行环境不同。没有据此判断 API Key 无效，也没有切换到 Mock。

为便于在普通 CMD 中验证，新增临时脚本：

~~~text
backend/.tmp-diagnostics/embedding_connectivity_probe_20261028.py
~~~

该脚本通过项目现有配置和工厂执行同一单文本请求，只输出脱敏状态、服务类型、异常类型、HTTP 状态（如适配器提供）、模型、维度、有限数值和耗时，不输出密钥、请求头或完整响应。建议在 backend 目录执行：

~~~cmd
"..\\.venv-test-313\\Scripts\\python.exe" .tmp-diagnostics\\embedding_connectivity_probe_20261028.py
~~~

本次仍未修改业务代码、依赖、`.env`、数据库或虚拟环境。真实 Embedding API 最小验证尚未完成。

### 需要理解的专业知识

- `curl -I` 对 HTTPS 地址返回 401 只能证明连接到达服务并被服务端处理，不能证明 POST JSON 请求、模型参数或 API Key 验证成功。
- `transport_injected=False` 只能说明应用没有注入测试传输层；是否获得供应商响应仍取决于当前网络环境、代理和服务端处理。
- 在不同终端执行相同 Python 代码时，代理、沙箱和网络出口可能不同，因此必须分别记录环境和结果。
- 可复现诊断脚本应避免打印 Authorization、API Key 和完整响应，并以退出码区分配置缺失与请求失败。
## 十七、百炼 Embedding 网络层诊断（2026-10-28）

本次严格没有调用 `embed_query()` 或 `embed_documents()`，没有发送模型输入、Authorization、API Key 或 JSON 请求体。新增并执行独立诊断脚本：

~~~text
backend/.tmp-diagnostics/embedding_network_probe_20261028.py
~~~

使用解释器 `.venv-test-313\\Scripts\\python.exe`，检查结果如下：

- HTTP 客户端：`httpx2` 2.16.0。
- `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`：均未设置。
- Python 客户端：`trust_env=True`；诊断客户端没有显式代理配置。
- DNS：目标主机解析成功，得到 2 个地址；未在记录中输出地址明细。
- HTTPS 探针：对 `/compatible-mode/v1/embeddings` 只发起不带认证、无请求体的 GET，请求超时上限为 5 秒。
- 结果：约 5.025 秒后得到 `ConnectTimeout`，没有 HTTP 状态码、响应正文或供应商响应。

这与普通 Windows CMD 中 `curl.exe -I` 收到 HTTP 401 的结果不同：普通 CMD 证据说明该环境可到达 HTTP 层，而当前 Codex 环境的 Python HTTPS 连接在有界超时内没有到达 HTTP 响应阶段。当前证据支持运行环境、网络出口或终端策略存在差异，但不能单独确定具体阻塞组件。没有修改代理、防火墙、注册表、业务代码、依赖、`.env`、数据库或虚拟环境。

本次属于 DNS/代理/HTTPS 网络诊断，不是真实 Embedding API 验证，也没有改变真实联调任务状态。

### 需要理解的专业知识

- DNS 成功只证明主机名能够解析，不等于 TCP、TLS 或 HTTP 请求成功。
- HTTP 401 说明请求到达了服务端 HTTP 层；`ConnectTimeout` 说明在有界时间内没有获得可用连接响应，不能据此判断认证失败。
- `trust_env=True` 表示客户端允许读取环境代理配置，但本次四个常见代理变量均未设置，且代码没有显式代理。
- 不带 Authorization 的 GET 探针只能验证网络层，不会验证 Embedding 模型、请求体或 API Key。

下一步：在收到普通 CMD 的实际诊断脚本输出后，对比 Python 解释器、代理、DNS、TLS 和网络出口；优先检查普通 CMD 是否也能执行同一个 Python 网络探针，再决定是否需要系统级网络策略排查。
## 十八、普通 Windows CMD 完成真实百炼 Embedding 单文本验证（2026-10-28）

根据用户提供的普通 Windows CMD 终端截图，确认以下命令已实际执行：

~~~cmd
"..\\.venv-test-313\\Scripts\\python.exe" .tmp-diagnostics\\embedding_connectivity_probe_20261028.py
~~~

截图显示：

~~~ini
credential_status=configured
service=OpenAICompatibleEmbeddingService
transport_injected=False
request=success
model=text-embedding-v4
dimension=1024
finite=True
elapsed_seconds=1.325
~~~

这次验证说明项目现有配置加载机制成功创建真实 `OpenAICompatibleEmbeddingService`，并通过真实 HTTP 传输完成了一次单文本 `embed_query()`。返回向量模型标识为 `text-embedding-v4`，维度为 1024，所有元素均为有限数值，耗时 1.325 秒。证据来自用户提供的终端截图；本次记录不输出 API Key、Authorization 或完整响应。

此前的无认证网络探针在同一普通终端返回 HTTP 401，说明该探针能够到达 HTTP 层；该 401 不是带配置的 Embedding API 调用失败。后续带项目配置的真实 Embedding 请求已经成功，因此此前 Codex 环境中的超时只能记录为运行环境差异，不能推断具体由某个系统组件导致。

本次仅验证单文本 Embedding 请求，没有验证真实文档上传、批量向量化、SQLite 持久化、查询向量化、相似度检索、Chat 或真实 LLM。数据库、业务代码、测试代码、配置、依赖和虚拟环境均未修改。

### 需要理解的专业知识

- 查询向量是把用户问题转换为向量后用于相似度检索的表示；文档向量和查询向量必须使用兼容模型及相同维度，才能进行可靠比较。
- `dimension=1024` 和 `finite=True` 证明本次返回向量通过了基本形状与数值校验，但不证明检索质量或整个 RAG 链路通过。
- Mock Embedding 只验证本地确定性流程；本次 `transport_injected=False` 且返回真实响应，才构成真实供应商单文本验证证据。
- 无认证探针返回 HTTP 401 与带 API Key 的业务请求成功属于不同层次：前者证明网络和 HTTP 层可达，后者还证明了本次认证和请求协议得到供应商接受。

下一步：在隔离测试数据库中验证真实文档向量化、向量存储、查询向量化和检索闭环；真实 DeepSeek LLM 联调仍保持未完成。
## 十九、真实百炼 Embedding 隔离数据库闭环验证（2026-10-28）

本次使用项目现有服务完成“测试文本 → 分块 → 真实文档向量化 → 隔离 SQLite 持久化 → 真实查询向量化 → 语义检索”。为避免触及开发数据库，新增诊断脚本和数据库：

~~~text
backend/.tmp-diagnostics/real_embedding_rag_closed_loop_20261028_011147.py
backend/.tmp-diagnostics/real_embedding_rag_closed_loop_20261028_011147.db
~~~

执行命令：

~~~cmd
"..\\.venv-test-313\\Scripts\\python.exe" .tmp-diagnostics\\real_embedding_rag_closed_loop_20261028_011147.py
~~~

配置和隔离证据：

- `provider=openai_compatible`
- `mock_enabled=False`
- `model=text-embedding-v4`
- `dimension=1024`
- `batch_size=10`
- 实际服务类型为 `OpenAICompatibleEmbeddingService`
- `transport_injected=False`
- 数据库为新的 `.tmp-diagnostics` SQLite 文件，不是 `backend/rag_kb.db`
- 运行前后 `backend/rag_kb.db` 文件指纹一致，输出 `real_database_unchanged=True`

测试文本是自行构造的无敏感差旅报销制度短文。文本直接传入现有 `save_document()`，由现有 `split_text()` 完成分块和入库；本次没有通过 HTTP 上传接口或文件解析器验证，因此“文件解析”仍不是本次闭环的验证范围。实际生成 `document_id=1`、`chunk_count=1`、`chunk_index=0`。

文档向量化结果：

- 调用现有 `embed_document()`。
- 真实文档 Embedding 请求 1 次；由于只有 1 个分块且批量上限为 10，没有发生额外批次。
- 请求成功，耗时 0.270 秒。
- `embedded_count=1`。
- 向量模型为 `text-embedding-v4`，维度为 1024。
- 数据库重新查询得到 1 条向量记录，分块关联正确，模型和维度一致，所有已读向量元素均为有限数值，记录数与分块数一致。

语义检索结果：

- 查询文本为与差旅交通费、住宿费、报销材料和标准相关的改写问题。
- 调用现有 `search_chunks()`，真实查询 Embedding 请求 1 次。
- 查询向量化和检索成功，耗时 0.162 秒。
- 返回 1 条命中；目标 `document_id=1`、`chunk_id=1`、`chunk_index=0` 命中。
- 余弦相似度分数为 `0.812466`。
- 检索使用服务当前模型和维度过滤，文档向量与查询向量均为 `text-embedding-v4`/1024。

本次验证了真实 Embedding 的单文档、单分块、隔离存储和语义检索链路，但没有调用 LLM，也没有验证 Chat、批量多分块请求、HTTP 上传文件解析或生产数据库迁移。没有修改业务代码、API 契约、数据库结构、配置、依赖或虚拟环境。

### 需要理解的专业知识

- 文档分块把长文本转换为可独立检索的片段；分块大小会影响请求批次、召回粒度和上下文长度。
- 文档向量和查询向量必须使用相同模型及兼容维度；本次数据库保存模型标识和维度，检索按这两个元数据过滤。
- 向量持久化成功不能只看接口返回，还要重新查询数据库核对记录、分块关联、模型和维度。
- 余弦相似度用于比较向量方向；`0.812466` 是本次测试文本和查询的实际相似度，不应直接当作生产阈值。
- 独立 SQLite 数据库和文件指纹对比是测试隔离证据；它不等于生产环境的迁移、并发和备份方案。

下一步：在隔离数据库中验证多分块批量向量化及 HTTP 上传接口，再决定是否执行真实 Chat/LLM 联调；真实 DeepSeek LLM 仍未接入验收。
## 二十、真实 HTTP 上传闭环尝试受本地数据库初始化环境阻塞（2026-10-28）

本次目标是通过真实 HTTP 完成文件上传、解析、分块、真实 Embedding、隔离 SQLite 持久化和检索。只读检查确认了实际路由和调用链：

~~~text
POST /api/v1/documents
  -> parse_document()
  -> split_text() / save_document()
  -> 隔离数据库
POST /api/v1/documents/{document_id}/embed
  -> get_embedding_service()
  -> embed_document()
  -> OpenAICompatibleEmbeddingService.embed_documents()
POST /api/v1/retrieval/search
  -> get_embedding_service()
  -> search_chunks()
  -> OpenAICompatibleEmbeddingService.embed_query()
~~~

实际上传路由为 `POST /api/v1/documents`，multipart 文件字段为 `file`，向量化路由为 `POST /api/v1/documents/{document_id}/embed`，检索路由为 `POST /api/v1/retrieval/search`。配置通过进程环境变量覆盖 `DATABASE_URL`，不修改 `.env`；应用默认的 `backend/rag_kb.db` 不作为本次目标。

新增本次专用诊断脚本：

~~~text
backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.py
~~~

计划使用的新数据库和测试文档均位于同一专用临时目录，目标数据库在执行前不存在。脚本首先初始化隔离 SQLite 表，然后启动临时 Uvicorn 进程，再发送真实 HTTP 请求。实际执行命令使用 `.venv-test-313`：

~~~text
.\.venv-test-313\Scripts\python.exe http_upload_rag_closed_loop_20261028_011525.py
~~~

本次在当前 Codex 环境中未能越过隔离数据库初始化阶段：进程在 `sqlite+aiosqlite` 独立数据库引擎初始化处无阶段输出并超时。随后只读检查确认没有启动中的 Python 服务、18080 端口无监听，也没有生成本次目标数据库或测试文档。由于无法确认后端进程已使用隔离数据库，本次没有启动服务、没有发起真实 HTTP 上传、没有调用解析器、没有调用真实 Embedding，也没有调用检索 API。

因此本次状态为：HTTP 上传、HTTP 解析/分块、HTTP 触发的真实 Embedding、HTTP 检索均未执行；不能把服务层前一阶段的真实 Embedding 闭环记录扩展为 HTTP 端到端通过。此前已完成的隔离服务层闭环记录保持不变。

### 需要理解的专业知识

- 服务层直接调用和 HTTP 端到端调用验证的是不同边界；后者还覆盖 ASGI 路由、multipart 解析、依赖注入和进程配置。
- 通过环境变量覆盖 `DATABASE_URL` 可以在不修改 `.env` 的情况下隔离后端进程，但必须先确认数据库连接初始化成功。
- 数据库隔离证据不足时，不能启动上传服务或把 API 成功响应当作安全证据。
- 本地 `sqlite+aiosqlite` 初始化超时属于当前运行环境的阻塞证据；具体原因待在普通 Windows CMD 中用同一脚本进一步确认，不能猜测为业务代码缺陷。

下一步：在普通 Windows CMD 中执行该临时脚本，确认隔离 SQLite 初始化、临时服务健康检查和真实 HTTP 请求；成功后再记录各阶段状态。
## 二十一、普通 Windows CMD 完成真实 HTTP 上传到语义检索闭环（2026-10-28）

根据用户提供的普通 Windows CMD 实际执行结果，确认此前准备的诊断脚本已经在普通 CMD 中完成真实 HTTP 端到端验证：

~~~text
backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.py
~~~

本次使用的隔离产物为：

~~~text
backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db
backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.txt
~~~

脚本通过环境变量将后端进程的 `DATABASE_URL` 指向上述新数据库，并报告 `real_database_path_used=False`。实际结果来自用户提供的普通 Windows CMD 输出，不是本次重新发起的请求。

### HTTP 上传、解析和分块

- 临时服务健康检查：`server_health=success`。
- 上传接口：`POST /api/v1/documents`，实际响应状态码为 201。
- 上传文档 ID：1。
- 上传后分块数量：2。
- 测试文件经过现有上传接口、解析器和分块/持久化流程；分块索引为 `[0, 1]`。
- 隔离数据库中实际查询到 1 条文档记录和 2 个文档块记录。

### 真实 Embedding 和持久化

- 向量化接口实际响应状态码为 200。
- 使用真实 `OpenAICompatibleEmbeddingService`，不是 Mock、Fake 或 MockTransport。
- 模型：`text-embedding-v4`。
- 向量维度：1024；向量长度为 1024；有限数值检查通过。
- 向量化数量：2，状态为 `completed`。
- 隔离数据库实际查询到 2 条向量记录，模型、维度和文档块关联正确。
- 真实 Embedding HTTP 请求共 2 次：1 次文档批量请求、1 次查询请求。

### 真实语义检索

- 检索接口实际响应状态码为 200。
- 返回结果数量：2。
- 目标文档命中：`True`。
- 第一个结果相似度约为 `0.80185975`，但 `marker_present=False`。
- 第二个结果相似度约为 `0.65625160`，且 `marker_present=True`，即包含测试文档唯一标记的目标分块排在第二位。

该排序现象说明目标文档和目标分块均被召回，但查询与两个分块的相关性排序仍需进一步调查。本次不修改检索算法、不擅自设置阈值，也不把单次排序结果解释为生产质量结论。

### 结束状态和边界

- `real_database_unchanged=True`，原 `backend/rag_kb.db` 未被修改。
- `server_exit_code=1`。
- `server_log_contains_error=False`。
- 后端退出码为 1 的具体原因尚未确认；不能据此声称服务正常退出。脚本的清理阶段会主动终止临时服务，但本次不据此推断退出码来源，列为待调查事项。
- 本次完成的是 HTTP 上传、解析、分块、真实 Embedding、隔离持久化和真实语义检索闭环。
- 本次没有调用 Chat 或真实 LLM，没有完成完整 RAG 问答闭环，也没有验证生产部署、多文档召回质量或重新向量化。

### 需要理解的专业知识

- HTTP 端到端验证比直接调用服务层多覆盖了 ASGI 路由、multipart/form-data 解析、依赖注入、进程环境配置和响应模型。
- 文档向量化和查询向量化必须使用同一模型及兼容维度；本次两条向量记录和检索返回元数据均为 `text-embedding-v4`/1024。
- “目标文档命中”不等于“目标分块排名第一”；分块内容、查询措辞和向量模型会共同影响相似度排序。
- HTTP 状态码 200/201 只证明接口响应成功，数据库查询仍是确认持久化的必要证据。
- 进程退出码与业务请求成功是两个独立维度；本次服务请求成功，但退出码 1 的原因仍待调查。

下一步：调查目标分块排序与查询措辞/分块边界的关系，确认临时服务退出码来源；随后再决定是否进行真实 Chat/LLM 联调。
## 二十二、检索排名与临时服务退出码只读诊断（2026-10-28）

本次没有发起真实 Embedding 请求、没有调用 LLM、没有运行测试，也没有修改数据库。检查对象包括：

- `backend/app/services/retrieval.py`
- `backend/app/services/vector_store.py`
- `backend/app/services/text_splitter.py`
- `backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.py`
- `backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.txt`
- `backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db`（SQLite `mode=ro` 只读连接）

### 检索排名调查

隔离数据库实际包含 1 条文档、2 个分块和 2 条 `text-embedding-v4`/1024 向量记录。只读查询得到的分块正文为：

- `chunk_id=1`、`chunk_index=0`：包含测试唯一标记 `RAG-HTTP-UPLOAD-20261028-A7`、出差结束后 10 个工作日提交、电子发票、行程单和审批记录。
- `chunk_id=2`、`chunk_index=1`：包含电子发票、行程单和审批记录、住宿费用城市级别上限、超标说明及部门负责人审批。

诊断脚本使用的查询为：

~~~text
出差报销应在什么时候提交，需要哪些材料，住宿费用超标如何审批？
~~~

检索实现使用余弦相似度：点积除以两个向量的范数；零向量返回 0.0，并将结果限制在 [-1, 1]。分数越大表示向量方向越相近、相关性越高。实现先按 `min_score` 过滤，再按 `(-score, document_id, chunk_index, chunk_id)` 排序，因此历史结果第一名分数约 `0.80185975`、第二名分数约 `0.65625160` 的排序符合当前代码预期。

唯一标记所在的第 0 块排名第二，不能单凭“包含唯一标记”判断算法错误。查询同时强调住宿费用超标和审批，第二块直接包含住宿上限、超标说明和审批语义；第一块更直接包含唯一标记、提交期限和材料。真实 Embedding 模型可能因此给第二块更高分。当前证据支持“分块语义差异导致的合理可能性”，但尚不足以排除模型表现、查询措辞或分块边界对排名的影响，列为待调查，不修改排序算法、阈值或分块参数。

现有精确去重逻辑使用 `(filename, chunk_index, text, model, dimension)`。本次两个分块的 `chunk_index` 不同，因此不会被去重；去重发生在排序前，但只移除完全相同的稳定键，不会改变这两个合法不同分块的相对排序或结果数量。

### 临时后端退出码调查

诊断脚本通过 `subprocess.Popen` 启动真实后端进程：

~~~text
[sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18080"]
~~~

子进程工作目录为 `backend`，环境变量中覆盖隔离 `DATABASE_URL`，并将 `stderr` 合并到 `stdout`：`stderr=subprocess.STDOUT`。健康检查和 HTTP 请求完成后，脚本在 `finally` 中调用 `server.terminate()`，等待最多 10 秒；超时才调用 `server.kill()`，随后读取 `server.returncode` 并输出 `server_exit_code=1`。因此该退出码是在清理阶段等待真实 Uvicorn 子进程后取得的，来源是后端子进程的 `returncode`，不是包装脚本自身的 pytest 或 API 状态码。

`server_log_contains_error=False` 的检测依据是：等待进程结束后读取合并的标准输出/错误文本，并用大小写敏感的字符串匹配检查是否包含字面量 `ERROR`。这只能说明采集到的合并输出中没有匹配该精确字符串，不能证明没有异常、没有小写错误、没有未刷新日志，也不能证明进程正常退出。现有日志不足以确定退出码 1 的根因；不能把它描述为正常退出。

当前证据缺口包括：退出信号/终止状态的更细粒度信息、Uvicorn 完整启动和关闭日志、清理前后的进程状态，以及是否是 Windows `terminate()` 行为导致的非零退出。下一步最小诊断应在不调用 Embedding 的条件下，使用同样隔离数据库启动一个本地健康检查服务，分别记录 `poll()`、`wait()`、进程是否自行退出、完整合并日志和显式关闭前后的退出状态；不应修改业务代码或据此修改退出处理。

### 需要理解的专业知识

- 文本块命中表示至少一个向量相似，但不保证包含人工指定标记的块排名第一。
- 余弦相似度的排序方向是降序；排序键和过滤阈值必须结合代码阅读，不能从结果数量反推。
- 去重键若包含分块索引、模型和维度，就能保留不同分块及不同向量空间的合法结果。
- 子进程退出码、HTTP 响应状态码和业务日志是三种不同证据；健康检查成功不代表后端最终退出码为 0。
- 合并 stdout/stderr 后只查找单一字符串属于弱日志判定，适合初筛，不足以定位进程关闭根因。

本次结论：检索排序符合当前实现，排名原因仍需通过更细的查询/分块对照实验调查；退出码 1 的根因未确认。历史 HTTP 闭环结果保持为历史证据，没有改写为本次新测试结果。
## 二十三、确认 Windows `Popen.terminate()` 与退出码 1 的关系（2026-10-28）

本次只读检查了历史诊断脚本和 `.venv-test-313` 中 Python 3.13.17 的 `subprocess.Popen` 实现，没有重新启动服务、没有访问数据库、没有调用 Embedding/LLM，也没有运行测试。

脚本的生命周期为：

1. 使用 `subprocess.Popen` 启动真实 Uvicorn 子进程，`stdout` 为 PIPE，`stderr=subprocess.STDOUT` 合并到 stdout。
2. 完成健康检查、HTTP 上传、向量化和检索后进入 `finally`。
3. 无条件调用 `server.terminate()`。
4. 调用 `server.wait(timeout=10)`；只有捕获 `subprocess.TimeoutExpired` 时才调用 `server.kill()`，再等待一次。
5. 最后读取 `server.returncode` 并输出 `server_exit_code`。

当前 `.venv-test-313` 的 Python 3.13.17 源码显示，Windows 分支的 `Popen.terminate()` 调用：

~~~python
_winapi.TerminateProcess(self._handle, 1)
~~~

因此，历史结果 `server_exit_code=1` 与脚本主动调用 Windows `terminate()` 的退出码语义一致。它不能被直接解释为后端业务崩溃，也不能被解释为 HTTP 上传、Embedding 或检索失败。

现有证据没有记录 `server.poll()` 在进入清理前的状态，也没有记录 `wait()` 是否抛出 `TimeoutExpired`。因此：

- 不能证明服务在收到终止请求前已经失败；健康检查和三个业务请求此前均已成功，但没有更细的退出前状态记录。
- 不能确认 `kill()` 是否实际执行；脚本只记录最终退出码，没有记录该分支。
- `server_log_contains_error=False` 只是合并日志中没有匹配大小写敏感的字面量 `ERROR`，不是正常退出证据。
- 现有日志不能区分主动 `terminate()`、`kill()`、服务自行退出或其他关闭异常。

结论：退出码 1 与主动终止行为一致，且这是当前最有力的解释；但运行时证据不足以完全确认本次具体走过哪个关闭分支。没有必要为此修改业务代码或立即重新运行真实 HTTP 流程。最小报告改进方案是未来诊断脚本分别记录 `request_flow_ok`、`server.poll()`、`terminate_called`、`wait_timed_out`、`kill_called`、`returncode` 和 `shutdown_mode`，把主动关闭的非零退出码与业务流程失败分开报告。

### 需要理解的专业知识

- Windows 下 Python 的 `Popen.terminate()` 使用 `TerminateProcess`，并传入退出码 1；这与 Unix 信号语义不同，不能直接把 1 当作应用异常。
- 子进程健康状态、HTTP 响应状态、关闭方式和最终退出码是独立维度。
- `stderr=STDOUT` 能合并两个输出流，但日志中没有 `ERROR` 不等于没有异常；还需要记录进程状态和关闭分支。
- 诊断脚本应把“业务流程成功”和“测试进程主动清理”分开建模，避免把清理结果当作业务验收失败。
## 二十四、真实查询措辞对检索排名的影响验证（2026-10-28）

本次在不修改业务代码、数据库或配置的前提下，使用历史隔离数据库只读加载两个已存在的 `text-embedding-v4`/1024 文档向量，并通过真实 `OpenAICompatibleEmbeddingService.embed_query()` 执行三次查询。新增诊断脚本：

~~~text
backend/.tmp-diagnostics/ranking_probe_20261028_013029.py
~~~

脚本使用 SQLite `mode=ro`，没有写入或重建：

- 历史隔离数据库仍包含 2 个目标分块和 2 条向量记录。
- 存储模型与服务模型均为 `text-embedding-v4`。
- 存储维度和查询维度均为 1024。
- 存储向量和查询向量的有限数值检查均通过。
- 服务类型为 `OpenAICompatibleEmbeddingService`，`transport_injected=False`。

本次实际发送 3 次真实查询 Embedding 请求，每个查询一次，无重试、无 Mock、无 LLM：

| 查询 | 目标语义 | chunk_id=1 / index=0 | chunk_id=2 / index=1 | 排名 |
| --- | --- | ---: | ---: | --- |
| A：公司差旅报销需要在什么时候提交，需要准备哪些材料？ | 提交期限和材料 | 0.67768337（1） | 0.66433188（2） | 分块 1 第一 |
| B：出差住宿费用超过标准时，需要履行什么审批流程，由谁负责审批？ | 住宿费超标审批 | 0.55152012（2） | 0.78852834（1） | 分块 2 第一 |
| C：出差报销应在什么时候提交，需要哪些材料，住宿费用超标如何审批？ | 综合查询 | 0.65625160（2） | 0.80185975（1） | 分块 2 第一 |

每次查询返回模型与维度检查均通过，耗时分别约为 0.261 秒、0.167 秒和 0.161 秒。查询 C 的分数与历史 HTTP 闭环记录一致，说明本次使用的是同一隔离数据库向量和同一模型配置。

### 结论与边界

- 查询 A 让包含唯一标记、提交期限和材料的第 0 块排名第一。
- 查询 B 让包含住宿费上限、超标说明和审批的第 1 块排名第一。
- 综合查询 C 仍让第 1 块排名第一，与历史结果一致。
- 结果支持“查询措辞和强调的语义主题会改变分块排名”的判断。
- 这不是检索算法错误证据；项目当前余弦相似度降序排序与三组分数一致。
- 相似度分数是向量空间中的相关性信号，不等于答案正确率、事实完整性或生产召回质量。
- 本次未修改排序、分块、阈值、去重逻辑或数据库；也未上传文档、执行 HTTP 闭环或调用 Chat/LLM。

### 需要理解的专业知识

- 查询向量会编码查询中被强调的主题；同一组文档分块在不同问题下可以产生不同排序。
- 包含唯一测试标记只是验证分块身份，不代表该标记本身决定语义相关性最高。
- 综合查询可能更偏向其中一个子主题；如果需要稳定覆盖多个主题，应评估 top-k、分块策略、查询拆分或重排，而不是直接修改余弦排序方向。
- 真实 Embedding 请求成功只证明模型调用和向量校验成功；排名质量需要独立评测集和明确指标。

下一步：如需继续调查，可在新的隔离数据库中对比不同分块大小、重叠比例和查询拆分策略；不得把本次三次查询结果直接转化为生产阈值。
## 二十五、真实 DeepSeek LLM 单请求与隔离 RAG Chat 闭环（2026-10-28）

本次先执行一次真实 DeepSeek LLM 单请求，再在既有隔离数据库上执行一次真实 Chat API 闭环。没有上传新文档、没有修改数据库、没有调用 Mock LLM、没有运行测试。

### 真实 LLM 单请求

诊断脚本：

~~~text
backend/.tmp-diagnostics/deepseek_llm_probe_20261028_013254.py
~~~

使用项目现有配置和 `create_llm_service()`，配置状态为：

- provider：`openai_compatible`
- Mock：关闭
- 模型：`deepseek-flash`
- 凭证状态：已配置（未输出密钥）
- 服务类型：`OpenAICompatibleLLMService`
- `transport_injected=False`

使用无敏感问题和最小知识库上下文发送 1 次真实 LLM 请求。结果：

- 请求成功。
- 返回答案非空。
- 返回内容长度：43 个字符。
- 耗时：约 6.601 秒。
- 未输出完整回答、API Key、Authorization 或供应商响应。

### 隔离 RAG Chat 闭环

历史隔离数据库只读核验通过：

~~~text
backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db
~~~

数据库中存在 1 条文档、2 个分块和 2 条 `text-embedding-v4`/1024 向量。新增诊断脚本：

~~~text
backend/.tmp-diagnostics/deepseek_rag_chat_probe_20261028_013328.py
~~~

脚本通过进程环境变量将临时后端的 `DATABASE_URL` 指向历史隔离数据库，并明确设置：

- `EMBEDDING_MOCK_ENABLED=false`
- `LLM_MOCK_ENABLED=false`
- Embedding 服务类型：`OpenAICompatibleEmbeddingService`
- LLM 服务类型：`OpenAICompatibleLLMService`

临时服务健康检查成功后，只发送 1 次 `POST /api/v1/chat`。该请求实际经过：

~~~text
Chat API
  -> 真实 Embedding 查询向量
  -> 隔离数据库语义检索
  -> RAG 上下文组装
  -> 真实 DeepSeek LLM
  -> ChatResponse
~~~

结果：

- Chat HTTP 状态码：200。
- 回答非空，长度 121 个字符。
- 来源数量：2。
- 两个来源均来自 `document_id=1` 和隔离测试文件 `http_upload_rag_closed_loop_20261028_011525.txt`。
- 来源 0：`chunk_id=1`、`chunk_index=0`、分数约 `0.69535360`，包含唯一标记。
- 来源 1：`chunk_id=2`、`chunk_index=1`、分数约 `0.69325518`，不包含唯一标记。
- Chat 请求内部产生 1 次真实查询 Embedding 请求和 1 次真实 LLM 请求。
- 隔离数据库指纹保持不变：`isolated_database_unchanged=True`。
- 临时服务记录 `server_exit_code=1`、`server_log_contains_error=False`；该退出码来自主动清理流程，不能写成服务正常退出，但不改变已经取得的 Chat HTTP 200 业务证据。

因此，本次在“单个既有隔离文档、单次 Chat 请求”的范围内完成了真实 Embedding → 检索 → RAG 上下文 → DeepSeek LLM → 来源响应闭环。没有把该结果扩大为生产部署、批量文档、并发稳定性或完整前端验收。

### 需要理解的专业知识

- RAG Chat 闭环不仅要验证 LLM 返回非空，还要核对来源是否来自同一次检索和隔离数据库。
- Chat 请求中的查询 Embedding 与文档向量必须使用相同模型和维度；本次均为 `text-embedding-v4`/1024。
- 来源分数和来源顺序反映检索结果，不等于 LLM 回答已经被事实核验。
- Mock LLM/Embedding 的离线测试验证协议和编排；本次 `OpenAICompatibleLLMService` 和真实 Embedding 请求才提供供应商联调证据。
- HTTP 200、回答非空和来源存在证明本次请求链路成功，不代表生产环境已具备认证、租户隔离、重试、审计和成本控制能力。

仍待验证：前端真实 Chat 展示、真实 LLM 错误/超时处理、批量和并发场景、生产部署安全，以及完整的真实模型评测。
## 二十六、前端真实 Chat 契约与交付文档检查（2026-10-28）

本次只读检查了前端 Chat 请求层、页面状态和 Markdown 来源展示，核对了后端 Chat/RAG 契约，并运行了前端已有质量命令。没有发起新的真实 Chat 请求，没有访问数据库，没有修改业务代码或配置。

### 前后端契约检查

前端 `frontend/src/api.ts` 的 `askQuestion()` 调用：

~~~text
POST /api/v1/chat
Content-Type: application/json
~~~

请求字段为 `question`、可选 `top_k`、`document_id`、`min_score`，与 `ChatRequest` 一致。响应字段 `question`、`answer`、`sources` 与 `ChatResponse` 一致；来源字段 `chunk_id`、`document_id`、`chunk_index`、`filename`、`text`、`score` 与 `ChatSource` 一致。

`frontend/src/App.tsx` 的 Chat 流程会清理本地问题首尾空白、显示用户消息、显示生成中状态，成功后展示回答和来源，失败后展示 `ApiError` 或网络错误提示。来源按全局唯一的 `chunk_id` 去重；由于后端文本块 ID 是主键，不同分块不会因正文相同而被错误合并。

回答使用自定义 React Markdown 节点渲染，支持标题、粗体、列表、段落和换行；没有使用 `dangerouslySetInnerHTML`，不可信原始 HTML 不会被当作 HTML 执行。`frontend/src/App.css` 提供对应样式，`index.css` 已移除 Vite 默认布局干扰并设置全宽 `#root`。

### 前端命令验证

在 `frontend` 目录执行：

~~~cmd
npm run lint
npm run build
~~~

实际结果：

- Node：v24.22.0
- npm：11.19.1
- `npm run lint`：退出码 0。
- `npm run build`：退出码 0；包含 `tsc -b` 和 Vite production build，31 个模块转换成功。
- 本次没有运行浏览器端到端验证，因此构建通过不等于浏览器真实 Chat 已验收。

### README 和启动文档检查

在本次修订前，根 `README.md` 存在与当前证据不一致的过期描述；以下条目是当时的历史检查记录，现已由本次文档修订处理：

- 仍把后续前端写成 Vue 3，实际项目是 React + TypeScript + Vite。
- 开头和大模型章节仍把真实 Embedding、真实 LLM 描述为尚未联调；当前已有真实百炼单文本/HTTP 检索和真实 DeepSeek 单请求/隔离 Chat 证据。
- 部分 Embedding 示例仍使用 `text-embedding-3-small`/1536，而当前实际联调配置为 `text-embedding-v4`/1024。
- README 的 Chat 示例仍强调默认 Mock LLM，未反映真实服务可通过配置启用；这作为本地 Mock 默认行为本身仍成立，但缺少真实联调边界说明。
- 前端启动命令和开发环境说明不完整，缺少与当前 `frontend/package.json` 对应的 `npm run dev`、`npm run lint` 和 `npm run build` 说明。

这些是文档交付问题，不影响本次已通过的前端静态检查；当时按要求没有直接重写 README；后续已在本次文档修订中处理。

### 需要理解的专业知识

- TypeScript build 只能证明类型检查和生产打包成功，不能证明浏览器、CORS、真实后端地址和用户交互全部成功。
- API 契约对照要同时检查请求字段、响应字段、错误结构和来源标识；仅检查 URL 不够。
- React 默认会转义字符串内容；使用 React 元素树渲染 Markdown 可以避免把不可信 HTML 注入 DOM。
- 前端来源去重应使用稳定的全局分块标识；本项目 `chunk_id` 是向量表主键，适合作为展示去重键。

本次结论：前端 Chat 静态契约和 lint/build 通过，未完成浏览器真实 Chat 验收；README 和启动文档需要后续最小修订，不能把本次构建结果写成端到端通过。
### README 与前端启动文档修订（2026-10-28）

本次目标是依据当前代码和已有证据修正交付说明，没有修改业务代码、测试代码、配置、依赖、数据库或虚拟环境。

检查范围包括根 `README.md`、`frontend/README.md`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/src/api.ts`、`frontend/src/App.tsx`、后端配置/路由/服务代码以及三份项目记录。核对结果：前端实际为 React + TypeScript + Vite；API 基地址由 `VITE_API_BASE_URL` 控制，缺省为 `http://127.0.0.1:8000`；Chat 使用 `POST /api/v1/chat`；根 README 仍有 Vue 3、旧 Embedding 模型/维度和真实服务未接入等过期描述，前端 README 仍是 Vite 模板。

实际修改：

- 根 `README.md`：更新技术栈、目录树、Mock/真实模型边界、`text-embedding-v4`/1024 配置、真实验证历史证据、API 清单、前后端启动命令、数据库初始化影响、Swagger/健康检查地址和生产限制。
- `frontend/README.md`：补充 Node/npm 与锁文件检查、按需 `npm ci`、`VITE_API_BASE_URL`、开发服务器、lint/build 和常见连接故障排查。
- 未新增技术决策记录：本次是文档事实校正，不产生新的架构取舍，因此 `TECHNICAL_DECISIONS.md` 无需新增 ADR。

本次实际运行的验证命令是在 `frontend` 目录执行的 `npm run lint` 和 `npm run build`；两者退出码均为 0，build 包含 TypeScript `tsc -b` 与 Vite production build，共转换 31 个模块。Node 为 v24.22.0，npm 为 11.19.1。本次没有重新运行后端全量测试、没有调用真实 Embedding/LLM API，也没有进行浏览器端到端 Chat 验收。后端 303 passed、真实模型和隔离 RAG Chat 等内容均为此前独立记录的历史证据，不是本次重新执行结果。

### 需要理解的专业知识

- README 的接口、配置和启动命令必须以代码为准；历史记录只能作为证据，不能替代当前实现核对。
- `npm run build` 能证明 TypeScript 编译和 Vite 打包通过，但不能证明浏览器、CORS、后端数据库和真实用户交互通过。
- `VITE_*` 变量会在前端构建时注入，不能存放 API Key；真实模型密钥只能由后端安全配置读取。
- “配置了 provider/model/key”只表示具备创建真实适配器的条件，不等于供应商请求成功。
### 浏览器真实 Chat 验收尝试（2026-10-28）

本次先进行只读检查并设置隔离启动条件，没有修改业务代码、测试、`.env`、依赖、数据库或前端源码。

已确认：

- 使用 `.\.venv-test-313\Scripts\python.exe`。
- 历史隔离数据库 `backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db` 以 SQLite `mode=ro` 打开成功，包含 `documents`、`document_chunks`、`document_chunk_embeddings` 三张表。
- 隔离库有 1 条文档、2 个分块、2 条向量；分块索引为 0/1，向量模型为 `text-embedding-v4`，维度为 1024。未输出完整向量，也未访问 `backend/rag_kb.db`。
- `DATABASE_URL` 可通过进程环境变量覆盖；本次计划使用绝对路径指向上述隔离数据库，并将 `EMBEDDING_MOCK_ENABLED=false`、`LLM_MOCK_ENABLED=false`，不修改 `.env`。
- `frontend/src/api.ts` 默认访问 `http://127.0.0.1:8000`，Vite 配置没有代理；计划使用独立的 8002 后端和 5174 前端端口。

实际尝试：

```powershell
$env:DATABASE_URL='sqlite+aiosqlite:///./backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db'
$env:ENVIRONMENT='development'
$env:EMBEDDING_MOCK_ENABLED='false'
$env:LLM_MOCK_ENABLED='false'
.\.venv-test-313\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

端口 8002/5174 检查为空闲，但当前受限执行环境无法访问本地监听套接字；健康检查请求返回 Windows 套接字权限错误，8002 没有进入可用监听状态。只终止了本次启动的 Uvicorn 进程。浏览器自动化原生通道也不可用，因此没有打开前端、没有提交 Chat 问题、没有调用真实 Embedding/DeepSeek API，也没有产生浏览器网络或控制台证据。

结论：数据库隔离条件已证明，但“后端可监听 + 浏览器可访问”的执行条件未满足。本次不能将浏览器真实 Chat 标记为完成，也不能把历史隔离 Chat HTTP 结果冒充浏览器结果。

### 需要理解的专业知识

- 进程环境变量可以覆盖 pydantic-settings 从 `.env` 读取的 `DATABASE_URL`，但必须在启动前确认最终连接串和数据库文件路径。
- 读取隔离 SQLite 的 `mode=ro` 只能证明历史数据完整，不能证明运行中的服务一定使用该文件；服务启动参数还需要独立核验。
- HTTP 业务成功、ASGI 进程存活和浏览器页面可访问是三层不同的验收证据。
- 受限执行环境中的 loopback 权限错误属于环境阻塞证据，不能推断为 FastAPI、RAG 或模型业务错误。
### 浏览器真实 Chat 验收结果（2026-10-28，用户提供截图）

本条记录依据用户提供的浏览器截图，不是本次重新发起的 API 请求或测试执行结果。

知识检索页面：

- 查询：`差旅报销申请需要哪些材料？如果住宿费超标，应当如何审批？`
- 页面显示 2 个检索分块。
- 分块 1 相似度约为 `0.7999`，分块 0 相似度约为 `0.6380`。
- 结果展示了文档 ID、分块索引、正文和相似度，符合当前前端检索结果展示契约。

Chat 页面：

- 同一问题显示了非空回答。
- 回答涉及电子发票、行程单、审批记录和住宿费超标审批。
- 页面显示 2 个来源，包含文件名、分块索引、相似度和引用文本。
- 回答显示知识库引用标记。

此前控制台曾出现 CORS 错误；后续截图中检索结果和 Chat 回答正常显示。本条记录不推断 CORS 错误的具体根因，也不声称本次修改了 CORS 配置。

验收边界：截图证明了页面展示、来源呈现和回答交互在该场景下可见；不能证明本次浏览器请求重新调用了真实百炼 Embedding 或真实 DeepSeek LLM，也不能替代历史真实模型联调、后端全量测试、并发稳定性、生产部署或安全审计。本次没有重新发送 API 请求、运行 pytest、调用真实模型或修改数据库。

### 需要理解的专业知识

- 浏览器截图是运行时 UI 证据，能证明用户可见结果，但不能单独证明后端请求所使用的 provider、模型或数据库。
- 检索分数、来源标识和回答正文应分别核对；页面显示来源不等于回答内容已经被人工判定为事实正确。
- CORS 错误和后续请求成功可以同时出现在不同请求或不同时间点；没有网络日志和响应头时，不应猜测具体根因。
- 真实模型验收需要结合请求链、配置、模型响应和非 Mock 证据，不能用 UI 展示替代。
## 二十七、首次提交前文档状态校正（2026-10-28）

本节只整理已有证据，没有重新运行测试、调用真实模型或修改业务代码。

### 已确认事实

- 学习日志已有早期记录：用户报告 test_rag_e2e.py 为 8 passed、全量为 265 passed。
- 后续普通 Windows CMD 记录显示使用 .venv-test-313、Python 3.13.17 和 pytest 9.1.1 执行全量测试，最终为 303 passed in 23.17s，0 failed，0 skipped。
- 当前文件不足以证明 265 与 303 对应的代码版本、执行轮次或测试范围差异，因此两者均保留为历史记录；本轮没有重新运行全量测试。
- 用户提供的浏览器截图直接证明知识检索页面展示两个分块及相似度，Chat 页面展示非空回答、两个来源和知识库引用标记。
- 截图不能证明该次浏览器请求重新调用了真实百炼 Embedding 或真实 DeepSeek；真实模型证据仍以此前独立的 API/隔离 HTTP 记录为准。
- 早期曾出现 CORS 错误，后续截图显示页面正常；其根因和是否通过配置修改解决，当前没有新增证据。
- 本次将公开文档中的项目本机路径改为 PROJECT_ROOT 占位或项目内相对路径，并补充 backend/pytest-of-*/ 忽略规则。

### 当前状态边界

浏览器知识检索与 Chat 页面展示：已完成（用户截图场景）。

整体浏览器真实 Chat 端到端：部分完成；仍缺少可追溯的本次请求 provider/模型证据，以及生产部署、并发稳定性和安全审计证据。

### 需要理解的专业知识

- 测试数量必须绑定执行时间、代码版本、测试范围和完整 pytest 汇总；不同轮次的数字不能直接比较或互相覆盖。
- 浏览器截图是 UI 运行时证据，能证明可见展示，不自动证明后端 provider、模型、数据库或请求链路。
- .gitignore 只控制 Git 是否将文件视为候选内容，不会删除本地文件；敏感配置和测试数据库仍需在提交前人工复核。