# 平台无关契约｜v1.2.3冻结说明

核心评估/决策逻辑不依赖腾讯元器、Dify、扣子或自研前端的专属字段。平台差异只通过Adapter/Executor进入平台无关契约。

| Schema | 作用 |
|---|---|
| `task_input.schema.json` | 公开任务、上下文、工具、安全/业务约束 |
| `candidate_plan.schema.json` | 候选技术方案 |
| `experiment_spec.schema.json` | 实验目标、统一成功标准、repeats与候选执行配置 |
| `workflow_result.schema.json` | 运行状态、指标可用性、Tool Trace、Evidence、Provenance、远端时间/ID |
| `evaluation_result.schema.json` | Evaluator独立评价、安全语义、人工升级与约束违规 |
| `decision_card.schema.json` | 可追溯结构化决策 |
| `comparison_result.schema.json` | 多候选聚合、Eligibility与推荐依据 |
| `evaluation_contract.schema.json` | BENCHMARK Private Gold或LIVE_POC验收合同统一后的评估契约 |

v1.2.3执行一致性补丁已刷新 `CONTRACT_FREEZE.sha256`，当前8套Schema均已冻结并校验通过。真实联调若只是腾讯元器字段名差异，应只改Adapter映射；现实数据确实无法由契约表达时，才进入显式版本升级。

## 指标可用性

Latency、Cost、Token采用 `value + availability + source + note`。`AVAILABLE / NOT_PROVIDED / NOT_APPLICABLE / ESTIMATED`语义明确；ESTIMATED必须有来源与说明。未知不得填0。

## LIVE来源门禁

LIVE会校验顶层source、Provenance、`executor_type=LIVE_EXECUTOR`、remote execution/raw response引用、指标source、Tool Trace、Evidence source与远端时间。FIXTURE/MOCK/CONTROLLED_FAULT仅改顶层标签不能通过。

该门禁是防御性一致性验证，不是密码学真实性证明；真实LIVE仍需要真实公网调用与原始响应证据链。

## v1.2.1 契约变化

8套Schema数量不变：`evaluation_contract` 升级为v1.1，新增tool policy三态、LIVE decision criteria、安全策略与业务约束追溯；`comparison_result` 升级为v1.3，增加跨币种比较状态和静态FX归一化输出。

## v1.2.3 契约变化

- `evaluation_result.schema.json` 升级为v2.3：新增结构化 `execution_plan_integrity`，记录Task/Candidate声明、实际工具、missing/unexpected/forbidden工具与违规原因。
- `comparison_result.schema.json` 升级为v1.4：候选聚合新增 `execution_plan_violation_count`，作为不可推荐硬门禁。
- 其余6套Schema结构未因本轮扩大。
