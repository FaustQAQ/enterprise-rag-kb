# Enterprise RAG Knowledge Base 项目路线图

状态定义：已完成表示有代码和测试/记录支持；进行中表示已有实现但验收未闭环；待开始表示尚未实施；待调查表示原因或方案尚未由证据确认。

## 当前状态

| 能力 | 状态 | 依据 |
| --- | --- | --- |
| 文档解析、切分、持久化 | 已完成 | backend/app/services 与对应测试 |
| 文档列表、详情、删除 | 已完成（后端） | backend/app/api/v1/documents.py |
| Mock Embedding | 已完成（离线） | embedding_service.py、test_mock_embedding.py |
| 向量存储和模型/维度隔离 | 已完成（本地） | vector_store.py、模型和测试 |
| Python 余弦检索 | 已完成（本地） | retrieval.py 及检索测试 |
| RAG 编排和空结果拒答 | 已完成（Mock） | rag_service.py、Chat 测试和端到端历史记录 |
| Mock LLM | 已完成（离线） | llm_service.py |
| DeepSeek/百炼真实适配器 | 已完成（隔离请求范围） | 历史记录证明真实 Embedding、真实 DeepSeek 单请求和隔离 RAG Chat 成功；本次浏览器截图不新增真实模型调用证据 |
| React 前端 API 接入 | 已完成（页面展示场景） | 用户提供截图显示检索结果、Chat 回答和来源；真实模型 provider 仍需独立证据 |
| 浏览器端到端流程 | 部分完成 | 用户提供截图证明知识检索和 Chat 回答/来源展示；真实模型调用、控制台/CORS 根因和完整运行时链路仍未由本次证据确认 |
| 生产安全和规模化 | 待开始 | 认证、迁移、索引、异步任务未完成 |

## P0：本地交付闭环

| 任务 | 状态 | 验收标准 | 依赖 |
| --- | --- | --- | --- |
| 启动后端并确认 health、Swagger、ReDoc、OpenAPI | 待验收 | 服务启动成功，四个地址返回预期响应 | 依赖安装、初始化数据库 |
| 新文档完整闭环 | 进行中 | 上传 TXT/DOCX/PDF，列表出现，向量化后检索和 Chat 返回真实来源 | 后端、Mock Embedding |
| 前端文档管理 | 进行中 | 列表、数量、上传和失败提示来自真实 API | API 层、后端 |
| 前端检索与问答 | 已完成（截图场景） | 用户提供截图显示 2 个检索分块、非空回答、2 个来源、分数、引用文本和知识库标记；空结果及错误状态仍依赖自动化/手工补充验收 | 文档闭环、Embedding、Mock LLM |
| 前端文档删除 | 待开始 | 调用 DELETE 后列表和关联数据刷新，失败不误报成功 | 后端删除接口 |
| 重复来源运行时排查 | 进行中 | 已确认现有 SQLite 中存在重复上传文档；服务层已按精确重复键去重，仍需运行时 HTTP 验收 | 隔离数据、运行中后端 |

## P1：测试和质量门禁

| 任务 | 状态 | 验收标准 | 依赖 |
| --- | --- | --- | --- |
| 后端目标测试环境修复 | 已完成（独立环境） | Python 3.13.17、requirements.txt 安装、pip check 通过；目标测试可执行 | 外部独立环境目录 受权限限制，实际环境位于项目内 .venv-test-313 |
| 后端全量测试 | 已完成（普通 Windows CMD） | 303 passed in 23.17s；0 failed；0 skipped；命令为 ..\.venv-test-313\Scripts\python.exe -m pytest tests -vv -s -o addopts= | 用户提供普通 CMD 实际执行日志；独立环境 Python 3.13.17、pytest 9.1.1 |
| 前端 lint/build | 已完成（最近一次） | npm run lint 和 npm run build 退出码为 0 | Node 依赖 |
| 前后端 HTTP 验收 | 已完成（历史隔离 HTTP） | 历史记录包含上传、向量化、检索和隔离 Chat；本次截图补充页面展示证据，不新增真实模型请求证据 | P0 |
| 来源去重回归测试 | 已完成（目标回归） | 检索服务和 Chat API 目标测试实际通过 | 独立 Python 3.13 测试环境 |
| Markdown 展示回归测试 | 部分完成 | 用户截图显示回答和引用标记可见；标题、粗体、列表、换行的逐项覆盖及原始 HTML 安全性仍需专门验收 | 前端测试或手工验收 |

## P2：真实供应商接入

| 任务 | 状态 | 验收标准 | 依赖 |
| --- | --- | --- | --- |
| DeepSeek LLM 真实联调 | 已完成（单请求/隔离 Chat） | 历史真实请求和隔离 Chat 证据成功；本次浏览器截图不证明重新调用真实 DeepSeek | 密钥、预算、网络许可 |
| 百炼 text-embedding-v4 真实联调 | 已完成（单文本验证） | 普通 Windows CMD 中真实请求成功；model=text-embedding-v4、dimension=1024、finite=True、1.325s；仅代表单文本验证 | 密钥、预算、网络许可 |
| 真实文档向量化—隔离存储—语义检索 | 已完成（单文档单分块） | 隔离 SQLite 中 document_id=1、1 个分块、1 条 text-embedding-v4/1024 向量；查询真实向量化后命中目标分块，score=0.812466 | 真实 Embedding 单文本验证、隔离数据库 |
| 真实模型重新向量化 | 待开始 | 模型/维度一致；失败保留旧向量；成功无重复 | 真实 Embedding 联调 |
| Mock/真实模式隔离 | 进行中 | development 可显式 Mock，production 不静默回退，查询和文档向量一致 | 配置工厂 |

## P3：生产工程化

| 任务 | 状态 | 验收标准 | 依赖 |
| --- | --- | --- | --- |
| Alembic 迁移 | 待开始 | 升级和回滚在隔离数据库验证 | 数据模型稳定 |
| PostgreSQL + pgvector | 待开始 | 迁移、向量类型、索引和性能基准完成 | 迁移工具、数据库 |
| 向量索引 | 待开始 | 召回和延迟基准明确 | pgvector、数据规模 |
| 后台向量化任务 | 待开始 | 状态、重试、幂等和失败恢复可观察 | 任务方案 |
| 认证授权和租户隔离 | 待开始 | 文档、检索、删除、向量化按租户鉴权 | 用户模型、安全设计 |
| 关键词检索与重排 | 待开始 | 混合检索和离线评测集完成 | 索引、评测数据 |
| OCR、加密 PDF、旧版 DOC | 待开始 | 支持范围和失败响应有测试 | 解析器方案 |

## P4：作品集和学习复盘

| 任务 | 状态 | 验收标准 | 依赖 |
| --- | --- | --- | --- |
| README 与实际结构统一 | 进行中 | React/Vite、路由、Mock 边界、启动命令和测试记录无矛盾 | 前端运行时验收 |
| 架构图 | 待开始 | 展示上传、解析、切分、存储、向量化、检索、RAG、LLM 和前端调用链 | 架构稳定 |
| API 示例和错误码表 | 进行中 | 示例与实际 Schema、状态码一致 | API 验收 |
| 求职作品集说明 | 待开始 | 项目摘要、难点、取舍、测试证据、边界和演示步骤 | README、架构图 |
| 项目完成后的全流程学习复盘 | 待开始 | 从 HTTP、数据库、Embedding、RAG、前端、测试到生产风险逐项解释并附证据 | P0-P3 主要任务 |

## 推荐顺序

1. 在隔离数据库上启动后端，完成浏览器联调。
2. 记录真实上传、向量化、检索和 Chat 响应，确认重复来源根因。
3. 补齐前端删除和必要回归测试。
4. 统一 README、目录树、架构图和 API 示例。
5. 仅在预算、密钥和网络许可明确后做真实 Embedding/LLM 联调。
6. 再规划迁移、pgvector、索引、后台任务和认证。
7. 最后完成全流程学习复盘和求职作品集。

### 真实 Embedding 最小验证记录

- 2026-10-28：使用 `.venv-test-313` 和项目现有 `create_embedding_service()` 创建 `OpenAICompatibleEmbeddingService`，凭证配置状态为“已配置”。
- 发送一次无敏感文本的真实 `embed_query()` 请求，未写入数据库、未上传企业文档、未调用 LLM，也未重试或切换到 Mock。
- 请求在 HTTP 连接建立阶段失败，错误类别为脱敏后的 `EmbeddingProviderError`，底层为 `httpx2.ConnectError`；没有供应商 HTTP 状态码和响应体。
- 因此模型、返回维度、有限数值和真实供应商成功响应均仍未确认。该任务不能标记为已完成。
### 第二次真实 Embedding 请求记录

- 2026-10-28：当前 Codex 环境再次使用真实 `OpenAICompatibleEmbeddingService` 发送单文本请求，确认未注入 MockTransport；约 5.3 秒后得到脱敏 `EmbeddingProviderError`，没有 HTTP 状态码和供应商响应。
- 普通 CMD 的 `curl.exe -I` 已返回 401，证明该终端具备 HTTPS 基础可达性，但仍不等于 POST Embedding 认证成功。
- 已准备 `backend/.tmp-diagnostics/embedding_connectivity_probe_20261028.py`，供普通 CMD 使用相同项目配置进行一次性验证。
- 模型、1024 维度和有限数值仍待真实成功响应确认；不得将本次失败或 curl 401 记录为真实 Embedding 验收通过。
### 百炼网络层诊断记录

- 2026-10-28：未调用 Embedding 方法；使用 `httpx2` 2.16.0、`trust_env=True`、无显式代理和无常见代理环境变量，DNS 成功解析目标主机。
- 不带认证、无请求体的 HTTPS GET 在当前 Codex 环境 5.025 秒后 `ConnectTimeout`，没有 HTTP 状态码。
- 普通 CMD 的 HTTP 401 与当前 Python 探针超时存在环境差异；真实 Embedding API 联调仍未完成。
### 真实 Embedding 单文本验证记录

- 状态：已完成（仅限单文本真实 API 验证）。
- 证据：用户提供的普通 Windows CMD 截图，使用 `.venv-test-313` 执行 `embedding_connectivity_probe_20261028.py`。
- 结果：真实 `OpenAICompatibleEmbeddingService` 请求成功；`text-embedding-v4`、1024 维、有限数值检查通过，耗时 1.325 秒。
- 边界：真实文档批量向量化、数据库存储、查询向量化、检索和 Chat 闭环仍待验证；真实 DeepSeek LLM 联调未完成。
### 真实 Embedding 文档检索闭环记录

- 状态：已完成（限定为自构造无敏感文本、单文档、单分块、隔离 SQLite）。
- 证据：`backend/.tmp-diagnostics/real_embedding_rag_closed_loop_20261028_011147.py` 的实际输出；文档向量化和查询向量化各 1 次真实请求。
- 持久化：1 个文档、1 个分块、1 条向量记录；模型为 `text-embedding-v4`，维度为 1024，数据库记录数与分块数一致。
- 检索：目标文档命中，`chunk_index=0`，相似度为 `0.812466`。
- 边界：本次直接使用 `save_document()`，未验证 HTTP 文件上传和解析器；未调用 Chat/LLM；多分块批量、真实模型重新向量化和生产数据库仍待验证。
### 真实 HTTP 上传到语义检索闭环记录

- 状态：环境阻塞，未完成。
- 已确认：上传路由为 `POST /api/v1/documents`，文件字段为 `file`；向量化和检索路由及调用链已根据实际代码确认。
- 本次尝试：使用 `.venv-test-313` 和临时诊断脚本准备隔离 SQLite 与临时 Uvicorn 服务，但当前环境在 `sqlite+aiosqlite` 隔离数据库初始化阶段超时。
- 结果：未启动服务、未发起 HTTP 上传、未调用 HTTP 解析/分块、真实 Embedding 或检索 API；不得标记为端到端通过。
- 保持完成状态：此前“真实 Embedding 单文本验证”和“服务层隔离数据库语义检索”仅代表各自范围内完成。
- 仍待验证：普通 Windows CMD 中的真实 HTTP 上传、API 编排、数据库持久化和检索闭环；Chat/真实 LLM 联调仍未完成。
### 真实 HTTP 上传到语义检索闭环成功记录

- 状态：已完成（范围限定为 HTTP 上传、解析、分块、真实 Embedding、隔离持久化和语义检索）。
- 证据脚本：`backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.py`。
- 隔离产物：`backend/.tmp-diagnostics/http_upload_rag_closed_loop_20261028_011525.db` 和 `.txt` 测试文件；`real_database_path_used=False`、`real_database_unchanged=True`。
- 结果：上传 201、文档 ID 1、2 个分块；向量化 200、2 个 `text-embedding-v4`/1024 向量；检索 200、2 条结果、目标文档命中。
- 排序待调查：唯一标记所在目标分块排名第二，分数约 0.65625160；第一条分数约 0.80185975 但不含唯一标记。
- 退出状态待调查：`server_exit_code=1` 且 `server_log_contains_error=False`，不能写成正常退出。
- 边界：Chat、真实 LLM、完整 RAG 问答、生产部署和生产召回质量仍未完成。
### 检索排名与临时服务退出码调查记录

- 排名结论：当前实现使用余弦相似度并按分数降序；历史结果 `0.80185975 > 0.65625160` 符合代码预期。唯一标记所在分块排名第二，可能与查询同时强调住宿超标/审批以及分块语义边界有关，仍待调查。
- 去重结论：两个分块的索引不同，现有精确去重键不会合并，未发现去重逻辑改变本次合法结果的证据。
- 退出码结论：`server_exit_code=1` 是脚本在 `finally` 终止并等待真实 Uvicorn 子进程后读取的 `returncode`；`server_log_contains_error=False` 只表示合并日志未匹配大写 `ERROR`，退出原因仍待调查。
- 本次未重新请求 API、未运行测试、未修改业务代码；上述数值均为历史 HTTP 闭环证据。
### Windows 临时服务退出码调查记录

- 只读检查 Python 3.13.17 Windows `subprocess.Popen.terminate()` 源码，确认其调用 `TerminateProcess(..., 1)`；历史 `server_exit_code=1` 与主动终止行为一致。
- 现有脚本无条件在 `finally` 调用 `terminate()`，只有 `wait(timeout=10)` 超时才进入 `kill()`；脚本没有记录该分支是否执行。
- 结论：不能把退出码 1 写成后端业务失败，也不能把没有 `ERROR` 写成正常退出；业务流程和关闭状态需要分开报告。
- 当前不重新运行真实 HTTP 流程；后续诊断脚本应增加关闭分支和 `poll()` 状态记录。
### 真实查询措辞与排名对照记录

- 状态：已完成（只读历史隔离数据库、三次真实查询向量）。
- 证据脚本：`backend/.tmp-diagnostics/ranking_probe_20261028_013029.py`；实际发送 3 次真实 `embed_query()`，未写入数据库。
- 查询 A（提交期限/材料）：chunk 1 排名第一，0.67768337；chunk 2 排名第二，0.66433188。
- 查询 B（住宿费超标审批）：chunk 2 排名第一，0.78852834；chunk 1 排名第二，0.55152012。
- 查询 C（综合问题）：chunk 2 排名第一，0.80185975；chunk 1 排名第二，0.65625160，与历史 HTTP 结果一致。
- 结论：查询措辞会影响排名；不代表答案正确率，也不构成修改排序算法的依据。
- 后续：分块边界、查询拆分、重排策略和独立召回评测仍待规划；Chat/真实 LLM 联调仍未完成。
### 真实 DeepSeek LLM 与隔离 RAG Chat 验证记录

- 真实 LLM 单请求：已完成。`OpenAICompatibleLLMService`、模型 `deepseek-flash`、非空回答、约 6.601 秒。
- 隔离 RAG Chat：已完成（单次请求范围）。历史隔离数据库中 1 条文档、2 个分块和 2 条 `text-embedding-v4`/1024 向量未被修改。
- Chat HTTP：200；回答非空；来源 2 条，均来自 `document_id=1` 的隔离测试文件。
- Chat 内部使用真实查询 Embedding 和真实 DeepSeek LLM；未使用 Mock。
- 临时服务 `server_exit_code=1`、`server_log_contains_error=False`，按主动终止语义记录，不作为业务请求失败。
- 边界：未验证前端浏览器展示、生产部署、并发/重试、批量文档和真实模型质量评测。
### 前端真实 Chat 交付检查记录

- 前端契约：已确认 `askQuestion()` 使用 `POST /api/v1/chat`，请求字段和 `ChatRequest` 一致，响应及来源字段和 `ChatResponse`/`ChatSource` 一致。
- 前端质量命令：`npm run lint` 退出码 0；`npm run build` 退出码 0，包含 TypeScript 检查和 Vite production build。
- Markdown/来源：React 节点安全渲染，无 `dangerouslySetInnerHTML`；按 `chunk_id` 去重，不合并不同合法分块。
- 浏览器页面展示验收：已完成（用户截图场景）；整体浏览器真实 Chat 端到端：部分完成，截图不能证明本次请求重新调用真实模型。
- 文档修订：README 仍需更新 React/Vite、真实模型验证证据、Qwen 1024 配置和前端启动命令；本次只记录问题，未直接修改 README。
### README 与启动文档交付说明（2026-10-28）

- 状态：已完成。
- 修改：根 `README.md` 与 `frontend/README.md` 已按当前代码补充 React + TypeScript + Vite、前后端启动、环境变量、API、数据库初始化、Mock/真实服务边界及故障排查说明。
- 验收标准：文档中的脚本名称、前端 API 地址、实际路由、Mock 开关和历史测试证据可由当前代码或已有记录追溯；未把浏览器端到端或生产部署写成已完成。
- 本次证据：前端 `npm run lint` 和 `npm run build` 均退出码 0；后端 303 passed、真实百炼/DeepSeek 和隔离 RAG Chat 为此前记录，不是本次重跑。
- 依赖关系：浏览器真实 Chat 验收依赖后端按预期数据库启动、CORS 配置正确、前端开发服务器启动；生产交付仍依赖认证授权、数据库迁移、异步任务、向量索引、稳定性和质量评测。

仍未完成：

- 浏览器真实 Chat 完整端到端链路验收（当前为部分完成）。
- 生产环境部署、并发稳定性、重试/限流和安全审计。
- 完整质量评测、认证授权、租户隔离、数据库迁移、异步向量化和生产向量索引。
- 架构图、求职作品集整理及项目完成后的全流程学习复盘。
### 浏览器真实 Chat 验收尝试（2026-10-28）

- 状态：未完成，环境阻塞。
- 已确认：历史隔离数据库可只读打开，包含 1 个文档、2 个分块和 2 条 `text-embedding-v4`/1024 向量；应用支持通过进程 `DATABASE_URL` 指向该绝对路径。
- 未完成：隔离后端未能在当前执行环境监听 8002，前端未启动，浏览器未操作，未产生新的真实 Embedding 或 DeepSeek 请求。
- 阻塞证据：健康检查访问本地套接字返回权限错误；浏览器自动化原生通道不可用。
- 验收标准：后端启动日志/配置确认使用隔离数据库；`/health` 成功；前端 API 地址指向该后端；浏览器一次 Chat 请求返回非空真实回答、来源和 Markdown 展示；控制台与网络请求无错误。
- 后续依赖：需要在允许本地 loopback 的普通 Windows CMD/桌面环境中启动隔离后端和前端，再进行一次浏览器验收。不能使用 `backend/rag_kb.db`，不能用 Mock 结果替代真实模型验收。
### 首次提交前文档状态校正（2026-10-28）

- 测试数量：保留 265 passed（早期用户报告，且与 test_rag_e2e.py：8 passed 同条记录）和 303 passed in 23.17s（后续普通 Windows CMD 完整汇总）两条历史证据。差异原因未由当前文件确认；本轮未重新运行测试。
- 浏览器展示：用户截图已证明知识检索分块、Chat 非空回答、两个来源和知识库引用标记在该场景可见，标记为已完成（截图场景）。
- 整体浏览器真实 Chat 链路：标记为部分完成；截图不证明该请求重新调用真实 Embedding 或 DeepSeek，生产部署、并发稳定性和安全审计仍未完成。
- 历史 CORS 错误与后续正常截图均保留；根因未确认，不推断是否通过配置修改解决。
- 本轮仅修正文档和 .gitignore，未运行测试、未调用 API、未操作数据库。