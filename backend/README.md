# 【小杨代小刘完成】实验执行后端/API v1.2

技术栈：Python + FastAPI（Python接口开发框架）+ Pydantic（数据校验库）+ httpx（HTTP客户端）+ pytest（Python测试框架）。

## 异步MVP API

- `GET /health`
- `POST /api/v1/runs` → `202 + run_id`
- `POST /api/v1/yuanqi/runs` → 腾讯元器原始前半段payload经Adapter转换后 `202 + run_id`
- `POST /api/v1/agent/intake` → 自然语言收成 Formal Case；`submit=true` 时再进入现有实验流水线
- `GET /api/v1/runs/{run_id}` → `QUEUED/RUNNING/COMPLETED/FAILED`

鉴权：`Authorization: Bearer <API_KEY>`，Key仅从环境变量读取。环境变量清单见 [`docs/ENV.md`](../docs/ENV.md)，模板见 [`.env.example`](../.env.example)。

POC 验证 Agent 只编译 Case，不写 Decision。未配置 `AGENT_LLM_URL` 时走确定性编译器（`planner_source=DETERMINISTIC`），不是 LIVE 模型调用。设计见 [`docs/agent/POC_VALIDATION_AGENT.md`](../docs/agent/POC_VALIDATION_AGENT.md)。

当前用进程内 `ThreadPoolExecutor` + 内存状态仓完成比赛MVP异步执行，避免引入Redis/Celery。它不是生产级分布式队列；进程重启会丢失未持久化任务。

## 两类运行上下文

- `BENCHMARK`：提交时验证Registry公开Input并私下编译Private Gold。
- `LIVE_POC`：允许动态case；必须提交运行前冻结的 `live_acceptance_contract`，不读取Private Gold。

## LIVE Executor

`EXECUTOR_MODE=LIVE` 时才允许调用真实Executor。支持 `YuanqiLiveExecutor` / `ExternalApiLiveExecutor` 骨架；端点、密钥、超时和响应映射全部外部配置。未配置真实密钥/端点时LIVE调用失败是预期行为，不允许回退成fixture冒充LIVE。

## v1.2.1 部署硬约束：single worker

当前比赛MVP使用 `ThreadPoolExecutor` + 进程内 `RUN_STORE` 保存异步任务状态，因此**必须以 single worker（单进程worker）方式启动**，例如：

`uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1`

不要在当前MVP直接使用多进程Uvicorn worker；否则POST可能落在进程A、GET落在进程B，产生 `run_not_found`。生产化时应改为Redis/数据库等外部持久化任务存储，但不属于本次比赛MVP范围。
