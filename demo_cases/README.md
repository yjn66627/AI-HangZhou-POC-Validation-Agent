# demo_cases｜演示 Case 数据包

> 本目录是 `DEMO_FREEZE_v1.0` 的脱敏展示层数据包，不是后端正式 API Contract。
> 正式冻结说明见 [`../docs/demo/DEMO_FREEZE.md`](../docs/demo/DEMO_FREEZE.md)。

---

## 一、用途

给尚未冻结的前端提供可导入的 Mock / Replay ViewModel：

- UI 排练走 L2 MOCK
- 路演保底走 L1 REPLAY
- 未来 `RealApiAdapter` 把真实后端映射成同一形状

禁止把本目录 JSON 当成最终后端 Contract。禁止 UI 依赖 `tc_`、`ta_`、Prompt 版本、Tool round。

---

## 二、文件

| 文件 | Demo ID | 内部 Decision | 默认 `source_mode` |
| --- | --- | --- | --- |
| [`DEMO-S.json`](DEMO-S.json) | 成功型：能跑且不外推 | `SUPPORT_CONTROLLED_TRIAL` | `L1_REPLAY` |
| [`DEMO-N.json`](DEMO-N.json) | 否决型：不进入生产推荐 | `DEFER` | `L2_MOCK` |
| [`DEMO-U.json`](DEMO-U.json) | 不确定型：证据不足 | `INSUFFICIENT_EVIDENCE` | `L2_MOCK` |
| [`DEMO-F.json`](DEMO-F.json) | 故障型：运行失败仍给 Final | `HUMAN_ASSISTED` | `L1_REPLAY` |

`DEMO-S` 锁定 [`TEST-P1`](../docs/cases/TEST-P1.md) 与 [`LIVE-1R` 公开摘要](../docs/live/LIVE1R_PUBLIC_SUMMARY.md)。L0 LIVE 仅在 health + smoke 通过且 Decision 匹配时由 Adapter 改写 `source_mode`；偏离则必须回到本回放包。

每个文件都包含：

- 顶层完成态（路演默认加载）
- `ui_states.running`：运行中刷新 / 等待
- `ui_states.exception`：至少一个边界 / 异常态，UI 不得因此崩溃

---

## 三、稳定字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `demo_id` | string | `DEMO-S` / `DEMO-N` / `DEMO-U` / `DEMO-F` |
| `formal_case_id` | string \| null | 对应 Formal Case；U/F 可为说明性锚点 |
| `freeze_version` | string | 必须等于 `DEMO_FREEZE_v1.0` |
| `source_mode` | string | `L0_LIVE` / `L1_REPLAY` / `L2_MOCK` |
| `case_status` | string | `pending` / `running` / `completed` / `failed` / `insufficient_evidence` |
| `title` | string | 页面标题 |
| `requirement` | object | 需求与约束短文案 |
| `candidate_solutions` | array | 候选方案；A = 系统路径，B = 错误外推 Baseline |
| `experiment_progress` | array | `{step, status}`，status 为 `done` / `running` / `failed` / `blocked` |
| `metrics` | object | 未知指标 `availability` 必须为 `NOT_PROVIDED`，禁止用 `0` 假装已测 |
| `evidence` | array | 必须能解释最终 Decision |
| `decision` | object | `result` 为展示用语，`code` 为内部档位 |
| `warnings` | array | 风险、限制、失败原因 |
| `ui_states` | object | `running` / `exception` 的局部覆盖 |

`decision.result` 只允许：

| result | code |
| --- | --- |
| 建议进入受控试运行 | `SUPPORT_CONTROLLED_TRIAL` |
| 暂缓，不进入推荐 | `DEFER` |
| 证据不足，继续验证 | `INSUFFICIENT_EVIDENCE` |
| 运行未完整成功，需人工辅助 | `HUMAN_ASSISTED` |
| 安全阻断 | `BLOCKED_BY_SAFETY` |

---

## 四、公开边界自检

放入本目录的内容必须同时满足：

- [x] 不含凭据、令牌、口令、验证码
- [x] 不含内部原始证据或未脱敏响应报文
- [x] 不含本机绝对路径
- [x] 不含个人邮箱、登录账号
- [x] 不含内部服务地址
- [x] 结论档位与 Decision Engine 一致，不把受控试运行写成可以上生产

详见 [`../docs/PUBLICATION_POLICY.md`](../docs/PUBLICATION_POLICY.md)。

---

## 五、前端接入约定

1. 页面只读上述稳定字段。
2. `source_mode` 必须驱动角标：真实运行 / 预置回放 / 演示数据。
3. 缺字段时 UI 不崩，展示 `warnings` 或空态。
4. 真 API 到来时只替换 Adapter，不改页面主逻辑。
5. 不得接 Dify；不得修改 Gateway / Runtime / Prompt。

脚本与口播见 [`../demo_scripts/README.md`](../demo_scripts/README.md)。

---

_本目录为公开级演示数据，不含私有评测答案与内部原始证据。_
