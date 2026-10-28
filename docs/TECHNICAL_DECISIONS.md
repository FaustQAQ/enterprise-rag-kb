# 技术决策记录

本文件记录当前代码和测试支持的技术选择；未确认内容标记为待调查。

## ADR-001：FastAPI、Pydantic 2 和异步 SQLAlchemy

- 选择：FastAPI、Pydantic 2.x、SQLAlchemy[asyncio]、aiosqlite。
- 原因：当前代码按依赖注入、Pydantic Schema 和 AsyncSession 分层；测试可使用 TestClient。
- 取舍：异步边界清晰，但测试辅助函数必须正确处理 coroutine；历史上曾把已生成的 ChatResponse 再传给 asyncio.run。
- 证据：backend/app/core、backend/app/schemas、backend/tests/conftest.py。

## ADR-002：SQLite JSON 向量存储

- 选择：默认 SQLite；向量保存为 document_chunk_embeddings.vector JSON，并保存 model、dimension。
- 原因：低门槛、可创建隔离测试库，不绑定供应商。
- 取舍：没有原生向量索引，不适合大规模生产。
- 待调查：PostgreSQL/pgvector 迁移、索引和性能基准。

## ADR-003：文档块和向量一对一

- 选择：DocumentChunkEmbedding.chunk_id 同时是主键和外键；文档块 document_id 与 chunk_index 唯一。
- 原因：每个 chunk 最多一条向量记录，重向量化可更新旧记录。
- 取舍：同一 chunk 不能并存多个模型向量；切换模型必须重新向量化。
- 证据：backend/app/models/document.py、vector_store.py、test_rag_e2e.py。

## ADR-004：字符级文本切分

- 考虑：token 切分、固定字符切分、优先语义边界的字符切分。
- 选择：按字符长度切分，优先空行、换行、句子、逗号和空白边界，必要时硬切。
- 取舍：字符数不是 token 数；真实供应商 token 预算仍待调查。

## ADR-005：保留 Mock Embedding

- 选择：MockEmbeddingService 使用本地确定性特征哈希；EMBEDDING_MOCK_ENABLED 显式开启。
- 安全规则：production 拒绝 Mock；关闭 Mock 且真实配置不完整时返回配置错误，不静默回退。
- 取舍：可重复、可离线，但没有真实语义检索质量。
- 证据：embedding_service.py、config.py、test_mock_embedding.py。

## ADR-006：OpenAI 兼容 Embedding 适配器

- 选择：保留 EmbeddingService 抽象，使用异步 HTTP 实现 OpenAICompatibleEmbeddingService。
- 边界：配置 API Key、Base URL、模型、维度、批量大小和超时；校验数量、索引、维度和有限数值。
- text-embedding-v4 特殊规则：支持 dimensions，每次最多 10 条文本。
- 取舍：减少 SDK 绑定，但兼容协议不保证供应商行为完全一致。
- 待调查：真实百炼账户下 URL、模型、维度、限流和计费。

## ADR-007：LLM 抽象、Mock 默认和 DeepSeek

- 选择：LLMService.generate_answer(question, contexts)；开发默认 MockLLMService；另有 OpenAI Chat Completions 兼容实现。
- 规则：提示模型只依据知识库上下文，上下文不足明确拒答。
- 取舍：Mock 能验收流程但不能代表答案质量；真实 DeepSeek 适配器有离线协议测试，真实联调仍待调查。

## ADR-008：RAG 来源和空结果拒答

- 选择：ChatResponse.sources 返回 chunk_id、document_id、chunk_index、文件名、正文和分数；无命中返回空列表并拒答。
- 取舍：来源正文增加响应体，但方便 UI 引用；生产还需权限过滤和敏感文本策略。
- 证据：rag_service.py、chat.py、test_chat_api.py。

## ADR-009：依赖注入和离线 HTTP 测试

- 选择：app.dependency_overrides 注入 Fake 服务；供应商 HTTP 使用 MockTransport。
- 取舍：离线协议测试通过不代表真实供应商联调通过。
- 证据：test_chat_api.py、test_embedding_integration.py、test_bailian_embedding.py、test_llm_integration.py。

## ADR-010：React/Vite 前端统一 API 层

- 选择：保持 React + TypeScript + Vite，新增 frontend/src/api.ts，页面调用真实文档、检索和 Chat API。
- 取舍：运行时验收和部分管理能力仍未完成；后端不可用时显示错误状态。
- 证据：frontend/src/api.ts、App.tsx、App.css；最近一次 lint/build 实际通过。

## ADR-011：Markdown 的无依赖安全降级

- 考虑：react-markdown/remark-gfm，或有限 Markdown 子集。
- 选择：当前环境安装过程未完成，因此暂不新增依赖；用 React 元素渲染需求范围内的 Markdown。
- 安全：不使用 dangerouslySetInnerHTML，原始 HTML 不执行。
- 取舍：不是完整 CommonMark/GFM；后续若需要表格、链接、代码块，应在依赖安装可用后评估维护良好的库。

## ADR-012：前端按 chunk_id 去重

- 检查证据：chunk_id 是向量主键，RAG 按命中一对一组装来源；后端未运行时无法确认实际 HTTP 重复位置。
- 选择：前端按稳定 chunk_id 去重；不同 chunk 即使正文相同仍保留。
- 原因：React key 不是去重机制，相同文本也不等于相同分块。
- 待调查：启动后抓取 retrieval/search 和 chat 的实际 JSON，确认数据库或后端是否仍产生重复命中。

## ADR-013：生产能力边界

- 已知限制：无认证授权和租户隔离；SQLite/JSON 向量无生产级索引；无 Alembic；向量化在 HTTP 请求内同步执行；无 OCR、混合检索、重排、对话历史和流式回答。
- 原因：当前目标是可解释的本地 B 方案和求职展示闭环。
- 交付边界：本地 Mock 验收不代表生产可用，也不代表真实供应商已联调。
- 后续：按 docs/PROJECT_ROADMAP.md 的 P0-P4 顺序推进。

## ADR-015：保留现有测试环境，先修复解释器可用性

- 事实：.venv/pyvenv.cfg 指向 Microsoft Store Python 3.13.14；标准 venv Python 和 pytest.exe 均在进程启动阶段失败，退出码 101。
- 进一步验证：用 Python 3.11 加载 venv site-packages 时，pytest 可导入但 pydantic_core 的 CPython 3.13 原生扩展产生 ABI ImportError，退出码 4。
- 选择：本次不重建 venv、不安装或升级依赖、不修改业务代码；先记录环境阻塞，待用户确认后提供可访问的同版本 Python 3.13 环境。
- 取舍：当前没有新的 pytest 通过数，但避免用错误 Python 版本产生误导性测试结果。

## ADR-016：没有可用 Python 3.13 时不创建新环境

- 事实：系统仅暴露 Microsoft Store Python 3.13 别名/路径，直接执行失败；没有找到可正常启动的 CPython 3.13 完整安装路径。
- 选择：保留现有 .venv，不创建 D:\\venvs\\enterprise-rag-kb，不安装依赖，不用 Python 3.11 替代。
- 原因：任务要求优先保证 Python 版本和原生扩展 ABI 一致；错误解释器会产生误导性测试结果。
- 取舍：目标 pytest 暂时无法执行，但没有污染现有环境或修改项目数据。
- 待调查：用户提供可启动的 Python 3.13 后，再按 requirements.txt 创建独立英文路径测试环境。

## ADR-014：检索层精确重复知识块去重

- 证据：只读检查 backend/rag_kb.db 发现文档 2、3、4 的文件名、块序号和正文哈希相同；文档 3、4 还具有相同的 text-embedding-v4 模型和 1024 维度。chunk_id 本身没有重复，重复来自独立文档上传。
- 选择：检索层按文件名、chunk_index、正文、model、dimension 五项组成稳定重复键；五项全部相同才合并命中。
- 保留规则：不同文件名、不同分块、不同模型或不同维度的结果不合并；Chat 复用检索命中，因此来源同步保持一致。
- 取舍：不修改或删除现有数据库记录，也不把“相同正文”单独当作删除依据；未来是否在上传阶段拒绝完全重复文档，仍需产品规则确认。
- 测试：新增检索服务和 Chat API 的隔离数据库测试；本次因 .venv 启动器无法在中文路径下创建进程，尚未得到后端 pytest 的实际通过数。

## ADR-017：使用同版本独立环境并隔离 pytest 临时目录

- 事实：用户提供的 Python 3.13.17 的用户环境解释器路径 可正常运行，版本为 3.13.17；原项目 .venv 保持不变。
- 约束：外部独立环境目录 父目录创建返回 WinError 5，因此无法在该位置创建环境。
- 选择：在项目目录创建独立 .venv-test-313，按现有 backend/requirements.txt 安装，不修改依赖版本；运行 pytest 时将 TEMP/TMP 指向可写的项目临时目录。
- 结果：pip check 通过；tests/test_retrieval_service.py 为 50 passed，tests/test_chat_api.py 为 17 passed，合计 67 passed。
- 取舍：项目目录产生了独立测试环境和临时目录；未覆盖原 .venv，未修改业务代码、测试断言或数据库。
- 未完成：全量 pytest 尚未在该环境中执行；外部独立环境目录 的权限限制仍待用户或系统管理员处理。
## ADR-018：全量测试没有最终汇总时不作通过判断

- 事实：使用 .venv-test-313 的绝对路径，并将 TEMP/TMP 指向已验证可写的项目临时目录后启动了 tests 全量 pytest。
- 结果：本轮等待期间执行被中断，未取得 pytest 最终汇总行和退出码；不能报告全量通过数、失败数或跳过数。
- 选择：保留此前 67 项目标测试通过记录，将全量测试标记为待重跑；不修改业务代码、测试断言或数据库来追求结果。
- 原因：pytest 只有在完整结束并输出汇总后，才能区分测试通过、失败、跳过和环境中断。
- 下一步：重新执行全量测试并记录完整输出；若失败，再按环境、隔离、测试逻辑或业务回归分类。
## ADR-019：将全量测试停滞归类为运行环境阻塞，暂不改业务代码

- 事实：全量 pytest collect-only 成功收集 303 项；详细运行在第一个百炼 Embedding 协议测试开始后 180 秒无进展。
- 证据：faulthandler 堆栈停在测试调用 asyncio.run 时的 Windows socket.py accept、_fallback_socketpair 和事件循环初始化；切换 Selector 事件循环策略以及运行最小 asyncio.run(asyncio.sleep(0)) 脚本仍超时。
- 判断：当前证据支持 Windows 执行环境的 asyncio socketpair/accept 初始化阻塞；尚不能证明 Embedding 适配器、MockTransport 或测试断言存在业务缺陷。
- 选择：不修改业务代码、测试断言、依赖版本或数据库；保留 303 项收集结果和 67 项已通过目标测试记录。
- 验收标准：在 socketpair/accept 可用的执行环境中，以同一独立 Python 3.13 环境完成全量 pytest，并获得最终汇总、退出码和失败分类。
## ADR-020：没有可用替代运行环境时不擅自安装或迁移

- 事实：WSL 命令存在但 status/list 返回 E_ACCESSDENIED；Docker CLI 存在但 Linux daemon named pipe 不存在；Python Launcher 报告没有已安装的 Python。
- 事实：系统 Python 3.13.17 和项目 .venv-test-313 都能启动并通过 pip check，但 asyncio.run(asyncio.sleep(0)) 在 10 秒内超时。
- 选择：不安装 WSL、Linux、Docker 或新依赖，不迁移项目，不创建新的测试环境；保留现有 303 项收集记录和 67 项目标测试通过记录。
- 原因：当前没有可验证的替代环境，继续操作不能产生可信的全量测试结果。
- 下一步：等待用户提供可访问的 WSL 发行版、修复 Windows asyncio 环境，或指定另一台可运行 Python 3.13 的主机。
## ADR-021：将 asyncio 阻塞归因到本地 socket 权限拒绝，暂不改 Python 或业务代码

- 事实：基础 Python 启动、-I -S 隔离启动和标准库路径均正常；两个 Python 3.13 解释器的 asyncio、socketpair 和 new_event_loop 都停滞。
- 直接证据：本地 TCP bind/listen 成功，但连接 127.0.0.1 返回 WinError 10013；faulthandler 显示 socketpair fallback 在 accept 停滞。
- 排除项：PYTHONHOME、PYTHONPATH、PYTHONASYNCIODEBUG、sitecustomize.py、usercustomize.py 不是已发现原因；切换 Proactor/Selector 策略也不能绕过 socket 权限。
- 判断：当前执行环境禁止或拦截本地 loopback socket connect。具体责任主体可能是防火墙、终端安全软件、应用沙箱或其他系统策略，仍待管理员确认。
- 选择：不重装 Python、不重建 venv、不修改系统策略、不修改业务代码；将全量测试保持为环境阻塞。
- 验收标准：在允许本地 loopback socket 的环境中，asyncio 最小探针应在 10 秒内输出 asyncio-ok，随后全量 pytest 应输出最终汇总。
## ADR-022：回环连接诊断保持只读，不把沙箱现象误判为防火墙结论

- 事实：IPv4 127.0.0.1 和 IPv6 ::1 均可 bind/listen，但 connect 都返回 PermissionError、errno 13、WinError 10013；localhost 同时解析为两个回环地址。
- 事实：netsh excludedportrange 和 advfirewall 查询在当前运行环境中不可用；Get-NetFirewallProfile/Rule 因 CIM 资源不可访问失败；默认防火墙日志路径不存在。
- 事实：当前 PowerShell 位于 Codex 受管控运行环境，存在沙箱包路径、workspace 权限配置和网络沙箱环境标识。
- 判断：已有证据支持受管控执行环境阻止本地 loopback connect，但没有证据区分防火墙、终端安全软件、沙箱策略或其他系统组件。
- 选择：不修改防火墙、端口范围、注册表、Python、虚拟环境或项目代码；不在当前沙箱内继续声称可完成全量 pytest。
- 下一步：在普通非沙箱终端或管理员可访问的诊断环境复跑同一探针；只有获得明确系统证据后，才提出系统级最小修复建议。
## ADR-023：以普通 Windows CMD 的完整 pytest 汇总作为后端全量验收证据

- 事实：用户提供的普通 Windows CMD 日志显示，使用 .venv-test-313、Python 3.13.17 和 pytest 9.1.1 执行 tests，最终为 303 passed in 23.17s，failed 0，skipped 0。
- 事实：普通 CMD 中的 asyncio 探针输出 ASYNCIO_OK，本地 TCP 回环探针输出 LOOPBACK_OK；此前受管控 Codex 执行环境中的 asyncio/socketpair 阻塞不能直接外推为整个 Windows 系统故障。
- 验收原则：pytest 必须完成收集、执行并输出完整最终汇总，且进程正常结束；collect-only 或超时记录不能替代全量通过证据。
- 选择：不修改业务代码、测试断言或依赖来解决此前阻塞；继续保留 .venv-test-313 与原 .venv 的用途隔离。
- 边界：303 项通过只证明当前离线自动化测试集通过，不代表真实 Embedding/LLM API、浏览器端到端流程或生产部署通过。
- 数据安全：继续使用测试夹具的临时数据库，不修改 backend/rag_kb.db；保留历史受限环境诊断记录，不将其写成当前项目失败。
## ADR-024：真实百炼 Embedding 首次验证只允许单请求且不写库

- 范围：使用项目现有配置和 `create_embedding_service()`，通过 `OpenAICompatibleEmbeddingService.embed_query()` 发送一条无敏感测试文本；不上传企业文档、不写入 SQLite、不调用 LLM、不重试、不切换 Mock。
- 安全措施：只输出凭证“已配置/未配置”状态、服务类型和脱敏错误类别；不输出 API Key、Authorization、完整响应或供应商错误体。
- 实际结果：工厂创建了真实 `OpenAICompatibleEmbeddingService`，请求确实进入真实 HTTP 客户端，但在连接建立阶段收到 `httpx2.ConnectError`，被转换为项目的 `EmbeddingProviderError`。没有取得 HTTP 状态码或供应商响应。
- 判断：本次证明了真实请求路径已被触发，但没有证明网络、凭证、账户权限或 `text-embedding-v4` 响应格式可用；模型、1024 维度和有限数值仍待真实成功响应确认。
- 选择：不修改适配器、不改变 Mock 机制、不修改数据库或依赖；先在允许访问百炼地址的普通非沙箱终端中重试同一单请求。
- 取舍：将“真实 Embedding 联调”保持为进行中，避免把配置存在或离线 MockTransport 测试误写成真实供应商验收通过。
- 待调查：连接失败的具体原因（网络出口、代理、终端策略或供应商地址可达性）尚未由本次请求单独确认。
## ADR-025：区分普通 CMD HTTPS 可达性与 Codex 环境真实 API 验证

- 事实：普通 Windows CMD 中对百炼 Embedding URL 执行 `curl.exe -I` 返回 `HTTP/1.1 401 Unauthorized`；这证明请求到达了 HTTPS 服务并被服务端处理，但未证明 API Key 或 POST Embedding 请求成功。
- 事实：当前 Codex 环境使用项目工厂创建了 `OpenAICompatibleEmbeddingService`，未注入 MockTransport，仅调用一次 `embed_query()`；约 5.3 秒后得到 `EmbeddingProviderError`，没有 HTTP 状态码或供应商响应。
- 选择：不重试、不切换 Mock、不写数据库、不上传文档、不修改业务代码；提供一次性本地诊断脚本，交由普通 CMD 执行。
- 安全边界：脚本不输出密钥、Authorization、完整供应商响应或响应向量，只输出脱敏状态和必要的校验摘要。
- 判断：真实 Embedding API 最小验证仍未完成。当前差异支持“普通 CMD 与 Codex 运行环境的网络行为不同”，但具体代理、沙箱或网络策略原因仍待调查。
- 下一步：在普通 CMD 中运行临时脚本，若获得真实响应，再记录模型、1024 维度和有限数值；成功后才安排隔离数据库中的文档向量化闭环。
## ADR-026：以无认证 HTTPS 探针区分网络层与 Embedding API 层

- 范围：本次只读取 HTTP 客户端和代理状态、解析百炼目标主机，并使用 5 秒超时发起无 Authorization、无请求体的 GET；明确不调用 `embed_query()`/`embed_documents()`。
- 事实：`httpx2` 版本为 2.16.0；四个常见代理环境变量均未设置；客户端 `trust_env=True`，诊断客户端无显式代理；DNS 解析成功得到 2 个地址。
- 事实：当前 Codex 环境的 HTTPS GET 约 5.025 秒后得到 `ConnectTimeout`，没有 HTTP 状态码或响应正文。
- 对照证据：普通 Windows CMD 的 `curl.exe -I` 返回 401，说明普通 CMD 可以到达 HTTP 层；不能将该结果直接外推到当前 Python/Codex 网络环境。
- 选择：不修改系统代理、防火墙、注册表、业务代码、依赖、数据库或虚拟环境；先在普通 CMD 运行同一无认证 Python 网络探针进行环境对照。
- 结论：本次只确认了 DNS 成功和当前环境 HTTPS 连接超时，未确认具体阻塞组件，也未完成真实 Embedding API 联调。
## ADR-027：确认百炼 text-embedding-v4 单文本真实请求成功

- 证据：用户提供的普通 Windows CMD 截图显示，使用 `.venv-test-313` 执行 `embedding_connectivity_probe_20261028.py`，输出 `request=success`、`service=OpenAICompatibleEmbeddingService`、`transport_injected=False`、`model=text-embedding-v4`、`dimension=1024`、`finite=True`、耗时 1.325 秒。
- 选择：将“百炼 text-embedding-v4 真实联调”标记为已完成，但限定为单文本请求验证；不扩大为整个 RAG 或 Chat 链路验收。
- 边界：本次没有验证真实文档批量向量化、SQLite 写入、查询向量化、检索排序、Chat 或真实 LLM；真实文档闭环保持待验证，DeepSeek LLM 联调保持未完成。
- 网络结论：普通 CMD 的无认证探针返回 401，随后带项目配置的真实 Embedding 请求成功。此前 Codex 环境超时只能作为环境差异记录，不能推断具体系统组件原因。
- 取舍：不修改业务代码、配置、依赖、数据库或虚拟环境；先复用现有适配器和配置完成隔离数据库闭环验证。
## ADR-028：真实 Embedding 闭环使用独立 SQLite 诊断数据库

- 目标：验证真实百炼 Embedding 从文档分块、向量化、持久化到查询检索的最小业务闭环，同时保护 `backend/rag_kb.db`。
- 方案：不使用应用全局数据库引擎，使用新建的 `.tmp-diagnostics/real_embedding_rag_closed_loop_20261028_011147.db` 和独立 AsyncEngine；复用 `save_document()`、`embed_document()`、`get_embeddings_for_document()` 与 `search_chunks()`。
- 证据：真实服务为 `OpenAICompatibleEmbeddingService`，未注入测试传输；文档和查询各发起 1 次真实请求；1 个文档、1 个分块、1 条向量记录成功保存；查询命中目标分块，score=0.812466；原 `backend/rag_kb.db` 指纹未变化。
- 选择：使用自构造无敏感文本，避免上传企业数据；不调用 LLM，不修改业务代码、数据库结构、配置或依赖。
- 取舍：本次直接调用文档持久化服务，因此验证了真实分块/存储/检索，但没有覆盖 HTTP 上传和文件解析器；单分块也没有验证多批次行为。
- 边界：单次语义命中不代表生产召回质量，也不代表 RAG/Chat 或真实 LLM 联调完成；相似度分数不能直接作为未经评测的生产阈值。
## ADR-029：HTTP 端到端验证必须先通过隔离数据库初始化门禁

- 背景：需要通过真实 HTTP 验证上传、解析、分块、真实 Embedding、持久化和检索，同时保护 `backend/rag_kb.db`。
- 方案：创建本次专用临时目录和新 SQLite 文件，通过子进程环境变量覆盖 `DATABASE_URL`，先初始化表并确认服务健康，再发送 HTTP 请求。
- 实际结果：当前 Codex 环境在独立 `sqlite+aiosqlite` 数据库初始化阶段超时；没有可靠的隔离数据库运行证据，因此没有启动服务或发送上传请求。
- 选择：保留诊断脚本和现场，不修改业务代码、数据库结构、配置、依赖或系统策略；不绕过数据库初始化，不退回真实项目数据库，也不切换 Mock 冒充成功。
- 取舍：本次无法增加 HTTP 端到端验收证据，但保护了原数据库和现有项目状态。
- 待调查：该环境中 `sqlite+aiosqlite` 初始化停滞的具体原因；应在普通 Windows CMD 中使用同一脚本和 `.venv-test-313` 复核。
## ADR-030：真实 HTTP 上传闭环使用隔离数据库，排序和进程退出单独验收

- 背景：此前只完成了服务层真实 Embedding/检索闭环，需要进一步验证 HTTP 上传、解析、分块、依赖注入和 API 编排，同时保护 `backend/rag_kb.db`。
- 证据：用户提供的普通 Windows CMD 输出显示，隔离数据库和测试文件位于 `backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.*`；健康检查成功；上传 201、向量化 200、检索 200；隔离库有 1 条文档、2 个分块和 2 条向量记录；`real_database_unchanged=True`。
- 真实模型：使用 `text-embedding-v4`，向量维度和长度均为 1024，有限数值校验通过；真实请求共 2 次，分别对应文档批量和查询向量。
- 检索边界：目标文档命中，但唯一标记所在目标分块排在第二位，分数约 0.65625160；第一结果分数约 0.80185975 但不含唯一标记。该现象列为查询与分块相关性及排名待调查，不通过修改算法或删除结果掩盖。
- 进程边界：`server_exit_code=1`、`server_log_contains_error=False`；退出码来源未确认，不能记录为服务正常退出。
- 选择：不修改业务代码、测试、配置、依赖、前端或数据库；将 HTTP 上传—检索闭环标记为本次范围内完成，但不扩展为 Chat、真实 LLM 或生产验收。
## ADR-031：不因单次排名或退出码现象擅自修改业务逻辑

- 背景：历史 HTTP 闭环中目标文档命中，但唯一标记所在分块排名第二；临时 Uvicorn 进程记录 `server_exit_code=1`，日志字面匹配未发现大写 `ERROR`。
- 检查证据：`retrieval.py` 使用余弦相似度并按分数降序排序；两个分块正文和查询语义不同；去重键包含文件名、分块索引、正文、模型和维度，两个分块不会被合并。诊断脚本在 `finally` 主动终止子进程后读取 `returncode`，日志检查是合并输出后的大小写敏感字符串匹配。
- 选择：不修改排序算法、相似度阈值、分块参数、去重逻辑或进程管理代码；将排名原因和退出码根因列为待调查。
- 原因：单次真实 Embedding 分数不足以证明算法错误，单一日志字符串缺失也不足以证明正常退出；需要最小对照实验和更完整进程状态证据。
- 下一步：先执行不调用外部 Embedding 的本地进程关闭诊断；排名方面使用隔离数据做查询措辞/分块边界对照，并记录完整结果后再评估是否需要业务调整。
## ADR-032：区分 Windows 主动终止退出码与业务流程结果

- 证据：历史诊断脚本在 `finally` 无条件调用 `server.terminate()`，随后 `wait(timeout=10)`；只有超时才调用 `server.kill()`；最终读取真实 Uvicorn 子进程 `returncode`。
- 证据：Python 3.13.17 Windows `subprocess.Popen.terminate()` 源码调用 `_winapi.TerminateProcess(self._handle, 1)`。
- 结论：历史 `server_exit_code=1` 与主动 `terminate()` 的 Windows 语义一致，是当前最有力解释；不能直接判定后端崩溃或业务请求失败。
- 证据缺口：脚本没有记录终止前 `poll()`、`wait()` 是否超时、`kill()` 是否执行以及服务是否自行退出，因此无法完全重建具体关闭分支。
- 选择：不修改业务代码、不修改现有诊断脚本、不重新调用真实 API；未来脚本报告中分离业务流程结果、主动关闭方式和最终退出码。
- 建议：新增诊断字段 `request_flow_ok`、`terminate_called`、`wait_timed_out`、`kill_called`、`returncode` 和 `shutdown_mode`，并仅在非预期退出或业务请求失败时报告进程验收失败。
## ADR-033：用多查询真实向量对照解释分块排名变化

- 背景：历史综合查询中，包含唯一标记的第 0 块排名第二，需要判断是排序错误还是查询主题差异。
- 方法：只读加载历史隔离 SQLite 中的两个 `text-embedding-v4`/1024 向量，使用真实 Embedding 服务对提交期限/材料、住宿费超标审批和综合问题分别生成一次查询向量，并复用现有余弦相似度及排序规则。
- 证据：查询 A 使 chunk 1 以 0.67768337 排名第一；查询 B 使 chunk 2 以 0.78852834 排名第一；查询 C 使 chunk 2 以 0.80185975 排名第一、chunk 1 以 0.65625160 排名第二。三次真实请求均成功，模型和维度校验通过。
- 判断：证据支持查询措辞及其强调的主题会改变排名；未发现当前余弦计算或降序排序错误。唯一标记用于确认块身份，不是语义相关性标准。
- 选择：不修改检索算法、阈值、分块、去重逻辑或数据库；将分块边界、查询拆分、重排和召回评测列为后续工作。
- 边界：三次查询不能证明生产检索质量，也不能把相似度解释为答案正确率；本次未验证 Chat 或真实 LLM。
## ADR-034：在历史隔离数据库上验证真实 DeepSeek RAG Chat

- 目标：在不重新上传文档、不修改 `backend/rag_kb.db` 的情况下，验证真实查询 Embedding、隔离检索、RAG 上下文和真实 DeepSeek LLM 的最小闭环。
- 证据：真实 LLM 单请求由 `OpenAICompatibleLLMService` 完成，模型为 `deepseek-flash`，回答非空，耗时约 6.601 秒；随后临时服务使用隔离数据库、Mock 关闭，Chat 返回 HTTP 200、非空回答和 2 条隔离来源。
- 来源证据：两个来源均为 `document_id=1` 的历史隔离测试文档，分别为 chunk 1/0 和 chunk 2/1；隔离数据库指纹未变化。
- 真实调用：单请求阶段 1 次真实 LLM；Chat 阶段 1 次真实查询 Embedding 和 1 次真实 LLM；未调用 Mock、未上传新文档。
- 选择：复用已有隔离数据库和现有 Chat/RAG 编排，不修改业务代码、配置、依赖或数据库结构。
- 边界：这是单文档、单次 Chat 的真实联调证据，不代表前端、生产部署、并发稳定性、错误恢复、成本控制或真实答案质量已验收。
- 进程说明：临时服务退出码 1 与 Windows 主动 `terminate()` 语义一致；业务 HTTP 200 和进程主动清理结果分开记录。
## ADR-035：前端 Chat 契约通过静态与构建检查，但不替代浏览器验收

- 事实：`frontend/src/api.ts` 的 Chat 请求使用 `POST /api/v1/chat`，请求字段与 `ChatRequest` 一致；响应和来源字段与 `ChatResponse`/`ChatSource` 一致。
- 事实：`App.tsx` 使用 React 元素渲染 Markdown，没有 `dangerouslySetInnerHTML`；来源按全局 `chunk_id` 去重；`npm run lint` 和 `npm run build` 均以退出码 0 完成。
- 选择：将前端契约和构建检查记录为已验证，但保留浏览器真实 Chat、CORS、运行时后端地址和错误交互为待验收。
- 边界：静态类型和生产构建不能证明浏览器端到端成功，也不能替代真实后端请求证据。
- 文档问题：README 中存在 React/Vue、真实模型状态、Embedding 示例维度和前端启动说明不一致；本次不在技术代码任务中直接重写 README，列入交付准备。
## ADR-036：浏览器真实 Chat 验收必须同时满足数据库隔离与本地网络可用

- 背景：浏览器验收需要运行后端、前端并发送一次 Chat 请求；历史隔离库已存在，但本次受限执行环境无法访问本地监听套接字。
- 证据：隔离 SQLite 以 `mode=ro` 读取成功，包含 1 个文档、2 个分块和 2 条 `text-embedding-v4`/1024 向量；应用支持用进程环境变量覆盖 `DATABASE_URL`。使用 `.venv-test-313` 启动 8002 的尝试中，健康检查出现本地套接字权限错误，服务未形成可用监听；浏览器自动化原生通道不可用。
- 选择：不切换真实项目数据库，不修改 `.env` 或业务代码，不重新上传文档，不调用真实模型请求；将浏览器验收保持为未完成。
- 边界：隔离数据完整不等于服务已使用该库；服务监听失败也不等于 RAG 业务失败。后续必须在本地 loopback 可用的普通桌面/CMD 环境复验。
## ADR-037：以用户提供的浏览器截图确认页面展示验收，并保留真实模型证据边界

- 背景：此前已有前端契约与构建检查，但浏览器页面展示曾标记为待验收；用户随后提供了 2026-10-28 浏览器截图。
- 证据：知识检索页面显示指定查询的 2 个分块，分块 1 约 `0.7999`、分块 0 约 `0.6380`，并展示文档 ID、分块索引、正文和分数。Chat 页面显示非空回答、电子发票/行程单/审批记录/住宿费超标审批内容、2 个来源及引用标记。
- 证据边界：截图是用户提供的历史运行时证据；本次没有重新发起 API 请求、运行测试或调用真实 Embedding/DeepSeek。此前出现过 CORS 错误，后续页面正常显示，但其根因和是否修改配置均未由本条证据确认。
- 选择：将知识检索页面展示、Chat 回答和来源展示记为完成/部分完成范围内的页面验收；不把截图等同于真实模型调用、全量测试、并发稳定性、生产部署或安全审计。