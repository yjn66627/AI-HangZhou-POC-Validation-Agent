# 环境变量｜ENV

> 本文件只记录变量**名**、用途和默认行为。  
> 真实密钥、真实地址不得写入仓库。模板见根目录 [`.env.example`](../.env.example)。

当前默认：**没有接入大模型 Key**。未填写 `AGENT_LLM_URL` 时，收案 Agent 走确定性编译（`planner_source=DETERMINISTIC`），不是 LIVE 模型调用。

本仓库后端会读取根目录 `.env`（已被 gitignore）。不要提交 `.env` / `.env.local`。

收案模型默认按 DeepSeek OpenAI 兼容接口接入 `deepseek-flash`。未填写 `AGENT_LLM_API_KEY`（或 `DEEPSEEK_API_KEY`）时**不会**调用模型，仍走确定性编译。

---

## 最小可跑后端（推荐）

本地演示可直接用根目录 `.env`：

```
API_KEY=local-demo-key
EXECUTOR_MODE=FIXTURE
MVP_WORKER_THREADS=4
AGENT_LLM_URL=https://api.deepseek.com
AGENT_LLM_MODEL=deepseek-flash
AGENT_LLM_API_KEY=<你的 DeepSeek API Key>
```

收案页 `/intake` 填同一个 `local-demo-key`。它是后端鉴权，**不是**模型 Key。

---

## 后端

| 变量 | 必需 | 默认 | 作用 |
| --- | --- | --- | --- |
| `API_KEY` | 调用 API 时必需 | 空（空则接口 503） | `Authorization: Bearer` 鉴权 |
| `EXECUTOR_MODE` | 否 | `FIXTURE` | 只有设为 `LIVE` 才允许真实 Executor；否则 Fixture |
| `MVP_WORKER_THREADS` | 否 | `4` | 进程内线程池大小 |
| `LIVE_EXECUTOR_KIND` | LIVE 时 | `YUANQI` | `YUANQI` 或 `EXTERNAL_PASSTHROUGH` |
| `LIVE_EXECUTOR_URL` | 外部 LIVE 时 | 空 | 外部 Executor 地址 |
| `LIVE_EXECUTOR_API_KEY` | 外部 LIVE 时 | 空 | 外部 Executor 鉴权 |
| `LIVE_EXECUTOR_TIMEOUT_SECONDS` | 否 | `20` | 外部 LIVE 超时 |
| `PRIVATE_GOLD_FILES` | 否 | 空 | 仅本机 Private Gold 覆盖路径；不得提交真实文件 |

## 收案 Agent（可选大模型）

未配置时收案页仍然能用，只是不调用模型。

| 变量 | 必需 | 默认 | 作用 |
| --- | --- | --- | --- |
| `AGENT_LLM_URL` | 要用模型时必需 | 空 | OpenAI 兼容地址，可填 `https://api.deepseek.com` |
| `AGENT_LLM_API_KEY` | DeepSeek 必需 | 空 | 模型服务 Bearer Key；也识别 `DEEPSEEK_API_KEY` |
| `AGENT_LLM_MODEL` | 否 | `deepseek-flash` | 当前默认 Flash |

模型只允许返回收案 JSON。若输出「可以上生产」或 `decision`，后端会丢弃并回退确定性编译。这仍不是 Tool LIVE，也不是生产可用。

## 腾讯元器 LIVE（未默认启用）

Gateway 专用模板：[`executor_gateway/.env.example`](../executor_gateway/.env.example)。说明：[`executor_gateway/RUNTIME_README.md`](../executor_gateway/RUNTIME_README.md)。

| 变量 | 作用 |
| --- | --- |
| `YUANQI_APP_ID` / `YUANQI_APP_KEY` / `YUANQI_OPENAPI_URL` | Gateway 调元器 OpenAPI |
| `EXECUTOR_GATEWAY_API_KEY` | Gateway `/execute` 鉴权 |
| `YUANQI_HTTP_TIMEOUT_SECONDS` | Gateway 超时，默认 20 |
| `YUANQI_EXECUTOR_URL` | 后端指向 Gateway，例如本机 `/execute` |
| `YUANQI_EXECUTOR_API_KEY` | 应与 Gateway 鉴权相同 |
| `YUANQI_RESPONSE_MAPPING_FILE` | 响应映射文件路径；未配置则 LIVE 失败，禁止猜字段 |
| `YUANQI_EXECUTOR_TIMEOUT_SECONDS` | 后端调 Gateway 超时，默认 20 |

未配齐时 LIVE 失败是预期行为，**不会**回退成 Fixture 冒充真实运行。

## 前端（可选）

模板：[`frontend/.env.example`](../frontend/.env.example)。

| 变量 | 作用 |
| --- | --- |
| `VITE_API_KEY` | 仅本地开发预填 `/intake` 的后端鉴权。会打进 Vite 前端包，**不要**把真实生产密钥写进去 |

更稳妥的方式：打开收案页后手填，密钥只留在浏览器会话。

---

## 不要做的事

- 不要把真实 `.env` 提交进 git
- 不要把模型 Key 写进前端代码或 DEMO 数据包
- 不要因为配了模型 Key 就对外说「已经可以上生产」或「Tool LIVE 已完成」
- 不要用 health 200 或 Fixture 结果冒充真实运行
