# 验收规则 v2.3

本版本的核心原则是：**运行前冻结验收标准，运行后只执行，不反向改标准。**

## 两类评估契约

- `BENCHMARK`：由后端 `CaseRegistry` 将 `Private Gold` 编译为 `EvaluationContract(source=PRIVATE_GOLD)`；Private Gold不得进入Executor、腾讯元器、LLM或Agent上下文。
- `LIVE_POC`：由业务方在实验提交前提供并冻结 `LIVE_ACCEPTANCE_CONTRACT`；不读取正式测试Private Gold。

## Evaluator必须执行

- 运行状态：仅 `SUCCESS` 可按完整成功处理；`PARTIAL/FAILED/CANCELLED/TIMEOUT` 不能被普通passed覆盖。
- 独立质量：候选自报分仅作观察，不作为最终质量分。
- 工具与安全：required/allowed/forbidden tools、未授权操作、真实安全违规。
- Evidence：Evidence type、claim linkage、target、action/result、Tool Trace引用与矛盾证据。
- Acceptance checks：`required_checks` 中每个结构化条件逐项验证。
- 业务阈值：质量、成本、延迟、错误数；不可用指标不得补0。
- 强制人工升级：`should_escalate=true` 优先于普通通过。

## Comparison门禁

默认：`minimum_pass_rate=0.8`、`maximum_failure_rate=0.2`、`maximum_timeout_rate=0.2`、`minimum_evidence_sufficiency_rate=0.8`、`allow_human_review=false`。

同一comparison group必须冻结相同的任务、成功标准、成本/延迟阈值、repeats、业务约束和禁止工具。候选特有工具允许不同，但不得改变成功标准。

真正安全违规、强制人工升级、证据不足、终止性失败，以及违反通过率/失败率/超时率/Evidence充分率门槛的候选不得进入推荐池。普通重复实验中的可容忍失败由显式阈值控制，不以“出现一次DEFER”永久封死。合格候选再按通过率、独立质量、Evidence充分率、失败率、真实成本、真实延迟和candidate_id进行确定性排序。


## v2.3 微补丁规则

- 外部布尔值必须严格解析；字符串 `"false"` 不得解释为True。
- Evidence要求按Task、Experiment、EvaluationContract、Private Gold取更严格结果。
- Task `allow_write_operations`、`prohibited_operations`、动态Claim Evidence均进入Evaluator硬门禁。
- LIVE_POC必须有实质Acceptance Contract：质量目标必填，成本/延迟必须明确 REQUIRED 或 NOT_APPLICABLE；Demo默认不能驱动正式Decision。
- `allowed_tools` 三态：未提供=UNRESTRICTED；`[]`=NONE_ALLOWED；非空=ALLOWLIST。
- Comparison跨币种无显式换算时不得按裸数值排序；允许配置静态 `base_currency + fx_rates`。
