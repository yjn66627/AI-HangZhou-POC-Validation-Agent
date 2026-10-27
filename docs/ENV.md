# 环境变量

真实密钥和真实环境文件不得提交。根目录 `.env.example` 只是字段模板；当前 `backend.app` 通过 `os.getenv` 读取进程环境，不会自动加载 `.env`。本地可按 README 在自己的 shell 显式设置变量。

## Backend 与执行器

| 变量 | 默认/用途 |
| --- | --- |
| `API_KEY` | 默认空；未配置时受保护 API 返回 503 |
| `EXECUTOR_MODE` | 默认 FIXTURE；只有显式 LIVE 才允许真实 Executor |
| `MVP_WORKER_THREADS` | 默认 4，进程内线程池 |
| `CASE_REGISTRY_PATH` | 默认空，不自动挂载额外评测 registry；仅使用你有权使用的文件 |
| `LIVE_EXECUTOR_KIND` | LIVE 模式的 YUANQI 或 EXTERNAL_PASSTHROUGH |
| `LIVE_EXECUTOR_URL` / `LIVE_EXECUTOR_API_KEY` / `LIVE_EXECUTOR_TIMEOUT_SECONDS` | 外部执行器配置，默认不连接 |
| `YUANQI_EXECUTOR_URL` / `YUANQI_EXECUTOR_API_KEY` / `YUANQI_RESPONSE_MAPPING_FILE` / `YUANQI_EXECUTOR_TIMEOUT_SECONDS` | 元器适配执行器配置；缺失配置不回退成假 LIVE |

Gateway 自身的变量名见 [Gateway 模板](../executor_gateway/.env.example) 与 [运行说明](../executor_gateway/RUNTIME_README.md)。API Key 只能通过安全运行时注入，不能提交到模板。

## 收案逻辑模块

`POST /api/v1/agent/intake` 复用已有 planner/service/LLM client，并使用与运行 API 相同的鉴权。未配置模型时使用确定性逻辑；预览不写运行记录，正式提交复用后台 pipeline。该状态只适用于本地源码候选，未更新线上服务。

模块支持 `AGENT_LLM_URL`、`AGENT_LLM_API_KEY`（兼容 `DEEPSEEK_API_KEY`）和 `AGENT_LLM_MODEL`。这些变量用于可选收案模型；本轮测试没有调用真实模型。当前预置回放和云端冻结响应不需要模型 Key。

## CloudFunction 公开合成示例

`ISOLATED_CLOUD_TEST_CREDENTIAL` 是继承 handler 使用的鉴权变量名；值由部署者在自己的安全配置界面生成并注入。本仓库仅提供空值模板。容器内部 `PORT` 由启动脚本设为 9000。

## 前端

`VITE_API_KEY` 会进入浏览器构建，不能存放生产或云端凭据。默认前端展示预置回放；收案路由只在本地候选中验证，未部署线上。模板见 [前端示例](../frontend/.env.example)。
