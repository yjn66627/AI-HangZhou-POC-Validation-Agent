# Tool 与实验执行架构

实验执行链负责运行候选并产出结构化结果；Tool 读取链负责在明确权限下读取结果。两者的能力和验证结论不能相互替代。

## 比赛提交版

历史本机演示链为：腾讯元器公网 Tool → Bridge / Backend → 受控实验结果。仓库中的 `GET /api/v1/runs/{run_id}` 读取 Backend 进程内记录；它要求稳定的单 worker（single worker）affinity，并未提供跨进程共享存储。启动时使用 `uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1`。

`executor_gateway/` 中还包含实验执行适配器及 Tool Runtime。代码存在、离线测试通过或接口返回 200，都不意味着任意企业数据的 LIVE 执行已完成。

## 赛后 P2 CloudBase

读取演示链为：腾讯元器 → CloudBase HTTP Gateway → Python HTTP 云函数 → 冻结 Fixture 响应。该函数不实时读取本机 RUN_STORE、不调用 Evaluator/Decision Engine，也不执行远端模型实验。

公开候选 `cloudfunction/` 保持请求与响应契约，数据改用独立构造的 SYNTHETIC_DEMO_DATA。handler 仅有 fixture 文件名调整；HTTP 启动还需要 `server.py` 与 `scf_bootstrap`。部署说明不包含真实资源标识、域名或凭据。

本机链与云端读取链可以分别测试；不能将合成 Fixture 的成功响应解释为动态企业 POC 的测量成功。
