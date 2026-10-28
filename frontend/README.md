# 前端开发说明

本目录是 React + TypeScript + Vite 前端工作台，当前页面通过后端 HTTP API 访问文档、检索和 Chat 功能。以下命令中的 %PROJECT_ROOT% 是项目根目录占位变量，请按本地路径替换或在当前终端定义。前端默认 API 地址为 `http://127.0.0.1:8000`；也可以用 `VITE_API_BASE_URL` 覆盖。项目未配置 Vite 代理，API 地址由 `frontend/src/api.ts` 直接读取。

## 前置条件

- Node.js 和 npm 可用。
- 后端已按根目录 README 启动并可访问健康检查。
- `package-lock.json` 与 `package.json` 位于本目录，安装时应使用锁文件。

在 Windows CMD 中检查版本和锁文件：

```cmd
cd /d %PROJECT_ROOT%\frontend
node --version
npm --version
if not exist package-lock.json echo ERROR: package-lock.json not found
```

只有在 `node_modules` 不存在或需要按锁文件恢复依赖时才执行安装：

```cmd
npm ci
```

不要用 `npm install` 随意改写锁文件，也不要在未确认网络和依赖变更范围时升级依赖。

## 配置后端地址

Windows CMD 当前窗口：

```cmd
set VITE_API_BASE_URL=http://127.0.0.1:8000
```

PowerShell 当前窗口：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
```

不设置时，代码使用同一个默认地址。修改后需要重新启动 Vite 开发服务器。

## 启动和检查

在 `frontend` 目录执行：

```cmd
npm run dev
```

Vite 默认地址为 `http://localhost:5173`。另开一个终端运行质量检查：

```cmd
npm run lint
npm run build
```

`npm run build` 会先执行 TypeScript `tsc -b`，再执行 Vite production build。它不能替代浏览器真实端到端验收。

后端默认检查地址：

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger：`http://127.0.0.1:8000/docs`

## 常见问题

- 页面提示无法连接后端：确认后端进程已启动、访问 `/health` 返回成功，并检查 `VITE_API_BASE_URL` 是否包含正确协议和端口。
- 请求返回 404：确认前端请求的是当前后端路由（例如 `/api/v1/chat`），并重新启动 Vite 以加载新的环境变量。
- CORS 错误：确认后端 `CORS_ORIGINS` 包含 `http://localhost:5173` 或 `http://127.0.0.1:5173`，并使用与配置一致的前端地址。
- Chat 返回 503：通常表示 Embedding 未配置或 Mock 未显式启用；先查看后端 Swagger 和 `.env` 配置，不要把错误改成固定模拟回答。
- Chat 返回 502：表示 LLM 服务调用失败；开发演示可保持 Mock LLM，真实服务则检查 provider、模型、超时和密钥配置，但不要把密钥写入前端。

当前前端 lint/build 的历史记录已在根目录学习日志中注明；用户提供的截图已证明知识检索和 Chat 页面展示场景，但完整浏览器链路及截图请求的真实模型归因仍需单独验收。