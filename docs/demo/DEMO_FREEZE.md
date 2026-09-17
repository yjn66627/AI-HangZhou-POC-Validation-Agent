# Demo 技术冻结｜DEMO FREEZE

> 版本：`DEMO_FREEZE_v1.0`
> 状态：设计已定，产物待审
> 冻结权：小杨
> 故事线 / UI：小林
> Case / QA：小刘
>
> 本文是比赛演示契约，不是 Formal Runtime Authority，也不是比赛封版。
> 不修改 Gateway / Runtime / Prompt / Evaluator / Decision Engine。

---

## 一、冻结是什么

Demo 技术冻结是一份**可版本化的演示契约**：现场只允许跑已点名的 Case，只允许走已声明的链路，失败时只允许按已写死的规则切换兜底。

它不是：

- 等 TEST-R3 / Tool LIVE 完成后再截图
- 比赛封版（那是后续的 `SOURCE_PUBLICATION_REVIEW`）
- 把 Mock JSON 升级成后端 Contract
- 把 UI 实现宣布为已完成

冻结后若改 Case、改链路或改兜底，必须升到 `DEMO_FREEZE_vN+1`，并同步改脚本与回放包。禁止只改 UI 文案、不改 Decision。禁止临场发挥。

当前仓库锚点：

| 项 | 值 |
| --- | --- |
| 正式基线 | `POST_C1D_PRE_REAL_TOOL_WINDOWS_BASELINE` |
| 唯一已证明真实端到端 Case | [`TEST-P1`](../cases/TEST-P1.md) / [`LIVE-1R`](../live/LIVE1R_PUBLIC_SUMMARY.md) |
| 冻结 Decision | `SUPPORT_CONTROLLED_TRIAL` |
| TEST-R3 | `FIRST TOOL LIVE CANDIDATE`，不得作为 3 分钟主线 |
| UI 实现 | 尚未开始；本冻结只约束它必须遵守的 Case / 链路 / 兜底 |

---

## 二、三条冻结轴

```
固定演示 Case  →  固定演示链路  →  固定兜底
 DEMO-S/N/U/F     L0 / L1 / L2      系统兜底 + 演示兜底
```

### 1. 固定演示 Case（3 + 1）

评委主叙事只用三个 Case；第四个是故障态，用来证明 fail-closed 是产品能力，不是事故。

| Demo ID | 评委一句话 | 仓库锚点 | 冻结的 Decision | 现场默认模式 |
| --- | --- | --- | --- | --- |
| `DEMO-S` | 能跑实验，且不把结论说过头 | TEST-P1 + LIVE-1R 公开口径 | `SUPPORT_CONTROLLED_TRIAL` | L0 LIVE；失败降 L1 |
| `DEMO-N` | 不会一味推荐上线 | 同一事实下「直接宣布生产可用」不可推荐 | `DEFER` | L1 REPLAY 或 L2 MOCK |
| `DEMO-U` | 证据不足时克制 | 无充分 Evidence / 无 Tool Trace 时 fail-closed | `INSUFFICIENT_EVIDENCE` | L1 或 L2 |
| `DEMO-F` | 运行失败仍给出 Final | Tool / 运行失败后进入人工辅助 | `HUMAN_ASSISTED` | 预置故障回放 |

硬约束：

- **3 分钟主演示只能是 `DEMO-S` / TEST-P1。** TEST-R3 不得作为主线。若 Tool LIVE 在后续冻结前通过，只能升为可选第二现场 Case，并单独打 `DEMO-R3-OPTIONAL`；未通过就保持候选，禁止临场改剧本。
- `DEMO-N` 的「否决」不是「AI 没价值」，而是「未证明项不足以进入生产推荐」。Baseline = 「5/5 PASS 所以可以上生产」；系统拒绝把该候选放入推荐。
- Case 包只使用展示层字段，外加冻结元数据。禁止 UI 依赖 `tc_`、`ta_`、Prompt 版本、Tool round。
- 指标未知处必须标 `NOT_PROVIDED` / 「未证明」，禁止填 `0` 假装已测。

数据包：[../../demo_cases/README.md](../../demo_cases/README.md)

### 2. 固定演示链路

现场对外只讲这一条产品链：

```
需求与约束 → 候选方案 → 实际运行/对照 → Evaluator → Evidence → Decision
```

不对外讲 Gateway 内部、SHA、Prompt Gate、`tc_` / `ta_`。Dify 已退出最终路线，不得作为演示方案。

技术上冻结三条实现路径，全部映射到同一 ViewModel：

| 路径 | 何时用 | 必须诚实标注 | 禁止事项 |
| --- | --- | --- | --- |
| L0 LIVE | 仅 `DEMO-S`，且 health + TEST-P1 smoke 通过 | 角标「真实运行」 | 不得把 FIXTURE / MOCK 标成 LIVE |
| L1 REPLAY | LIVE 超时、5xx、tool_fail、Decision 偏离，或 N/U/F | 角标「预置回放」 | 不得口头说「刚才真实跑的」 |
| L2 MOCK | 回放包缺失或纯 UI 排练 | 角标「演示数据」 | 不得进入比赛主演示，除非 L0/L1 都不可用 |

链路冻结清单（现场不得增减）：

- 入口：Demo 控制台一键打开 `DEMO-S`
- 后端：Backend → Gateway → Executor → Workflow Result → Evaluator → Decision Engine → Comparison
- 对照：Candidate A = 系统决策路径；Candidate B = 「直接宣布生产可用」的错误 Baseline（不是另一个未验证模型）
- 展示：现场必走首页、需求与约束、候选方案、实验进度、对照结果、Evidence、Decision；失败/证据不足页绑定 `DEMO-U` 与 `DEMO-F`
- 不进入演示链路：Dify、未审计 D1 Real Tool Adapter、腾讯元器未验证 Tool、Private Gold、原始报文

`DEMO-S` 的 LIVE 口径与 LIVE-1R 公开摘要锁定为同一组数字：

| 检查项 | 冻结值 |
| --- | --- |
| HTTP 200 | 5 / 5 |
| Workflow SUCCESS | 5 / 5 |
| Evaluation PASS | 5 / 5 |
| Decision | 全部 `SUPPORT_CONTROLLED_TRIAL` |
| Comparison eligible | `true`（仅针对受控试运行，不针对生产上线） |

现场若跑出其它档位，视为演示事故：立刻降到 L1 回放，而不是解释「这次不太一样」。

### 3. 固定兜底

兜底分两层。

**系统兜底（产品卖点，用 DEMO-U / DEMO-F 讲出来，不要藏）：**

| 条件 | Decision |
| --- | --- |
| 证据不足 | `INSUFFICIENT_EVIDENCE`，不允许 PASS |
| 安全违规 | `BLOCKED_BY_SAFETY` |
| 需人工但无人工能力 | `DEFER` |
| 运行未成功 / Tool 失败 | `HUMAN_ASSISTED`；Gateway 在非 SUCCESS 后进入 `FINAL_ONLY` |
| 超时 | 不按成功处理 |

**演示兜底（路演保命）：**

```
开场前 60s 静默 smoke
        |
        +-- 通过 --> 尝试 L0 LIVE
        |                |
        |                +-- Decision 匹配 DEMO-S --> 角标「真实运行」
        |                +-- 超时 / 5xx / 档位偏离 --> L1 回放
        |
        +-- 失败 --> 直接 L1 回放（评委面前不重试超过一次）
                         |
                         +-- 回放包存在 --> 角标「预置回放」
                         +-- 回放包缺失 --> L2 MOCK，角标「演示数据」
```

切换规则：

1. 开场前 60 秒做一次静默 smoke；失败则开场即 L1，不在评委面前重试超过一次。
2. LIVE 一旦偏离冻结 Decision，立即切 L1，UI 必须换角标。口播见 [../../demo_scripts/FAILOVER.md](../../demo_scripts/FAILOVER.md)。
3. 禁止无角标静默切 Mock。无角标切 Mock = 造假。
4. 回放包只含脱敏 ViewModel + 公开级聚合数字，不含原始报文、凭据、内网地址。准入规则见 [`../PUBLICATION_POLICY.md`](../PUBLICATION_POLICY.md) 与 [`../../public_artifacts/README.md`](../../public_artifacts/README.md)。
5. 网络 / 投影故障的最后一档：预先导出 Decision 页与对照页的脱敏截图到 `public_artifacts/demo/`，口播明确「静态截图」。当前目录尚无截图；有内容再建子目录。

---

## 三、ViewModel 与 Decision 映射

协作手册里的「做 / 不做 / 继续验证」必须映射到已冻结 Decision enum，不能另造前端结论。

| ViewModel `decision.result`（展示用语） | 内部 `decision` | 用于哪个 Demo |
| --- | --- | --- |
| 建议进入受控试运行 | `SUPPORT_CONTROLLED_TRIAL` | DEMO-S |
| 暂缓，不进入推荐 | `DEFER` | DEMO-N |
| 证据不足，继续验证 | `INSUFFICIENT_EVIDENCE` | DEMO-U |
| 运行未完整成功，需人工辅助 | `HUMAN_ASSISTED` | DEMO-F |
| 安全阻断 | `BLOCKED_BY_SAFETY` | 仅错误页，不进 3 分钟主线 |

禁止把 `SUPPORT_CONTROLLED_TRIAL` 译成「建议做 / 建议上线 / 可以上生产」。这与 [`../team/TEAM_ROLES.md`](../team/TEAM_ROLES.md) 的结论口径一致。

稳定展示层字段：

| 字段 | 用途 |
| --- | --- |
| `demo_id` | 冻结 Case 编号 |
| `formal_case_id` | 对应 Formal Case，可为空 |
| `source_mode` | `L0_LIVE` / `L1_REPLAY` / `L2_MOCK` |
| `case_status` | `pending` / `running` / `completed` / `failed` / `insufficient_evidence` |
| `candidate_solutions` | 候选列表 |
| `experiment_progress` | 实验步骤 |
| `metrics` | 质量 / 成本 / 延迟等；未知为 `NOT_PROVIDED` |
| `evidence` | 可展示证据摘要 |
| `decision` | 展示结论 + 内部档位 + 理由 |
| `warnings` | 风险、限制、失败原因 |

未来 `RealApiAdapter` 只做字段映射；页面不直连 Contract。字段变化优先改 Adapter，不优先重写页面。

---

## 四、允许 / 禁止表述

| 允许 | 禁止 |
| --- | --- |
| 集成已证明 | 可以上生产 |
| 质量已达标 | 生产可用 |
| 支持受控试运行 | 成本可控 |
| 主链路已跑通 | 稳定性已验证 |
| 5/5 重复通过 | 并发没问题 |
| 证据不足，继续验证 | 我检查过了，根因就是 X |
| 现场链路不稳定，切换到已冻结回放 | 假装刚才是真实跑通 |
| TEST-R3 是 Tool LIVE 候选 | 把 TEST-R3 当成已证明主演示 |

任何人（包括演示、README、Issue 评论、PPT）都不得越过 Decision Engine 的输出档位。

---

## 五、剧本结构

详细口播与点击路径见 [../../demo_scripts/](../../demo_scripts/)。

| 版本 | 结构 | 依赖 Case |
| --- | --- | --- |
| 3 分钟 | 痛点 30s → 输入 20s → 实验 40s → 对照 40s → Decision 30s → 亮点 20s | 只跑 `DEMO-S` |
| 5 分钟 | 痛点 → 产品 → Case → 实验 → Evidence → Decision → 安全/异常 → 架构与价值 | `DEMO-S` +（`DEMO-N` 或 `DEMO-U`）；`DEMO-F` 一键待命 |

---

## 六、治理

| 事项 | 约定 |
| --- | --- |
| 冻结权 | 小杨 |
| 故事线与 UI | 小林 |
| Case / QA 复测 | 小刘 |
| 变更 | 出 `DEMO_FREEZE_vN+1`，同步改脚本与回放包 |
| Git | 独立分支 / 独立 PR；不碰 `executor_gateway/`、`experiment/` 核心、Prompt 资产 |
| 公开边界 | Private Gold、原始报文、凭据、内网地址不得进入 Demo 包 |

---

## 七、冻结验收

过了才算「⑪ Demo 技术冻结」完成。当前 `v1.0` 完成的是**设计与脱敏数据包 / 脚本**；UI 实现与 L0 自动切换仍属工作包 A，不得据此把 UI 标为已完成。

设计与数据包验收：

- [x] 四个 Demo JSON 字段一致，Evidence 能解释 Decision
- [x] `DEMO-S` 锁定 TEST-P1 / LIVE-1R 公开口径，Decision 只能是 `SUPPORT_CONTROLLED_TRIAL`
- [x] L0 / L1 / L2 规则与口播已写明
- [x] 3 分钟脚本只依赖 `DEMO-S` + 对照页 + Decision 页
- [x] 5 分钟脚本额外走通 N 或 U，并准备 F 的一键入口
- [x] 全文不把 Dify 作为最终方案，不出现「可以上生产」作为系统结论
- [x] 回放包通过公开边界自检（无凭据、无原始报文、无内网地址）

待 UI 接入后才算完全通过：

- [ ] 四个 Demo JSON 可被前端 Adapter 加载
- [ ] `DEMO-S` 在 L0 可用时 Decision 只能是 `SUPPORT_CONTROLLED_TRIAL`；偏离则自动 L1
- [ ] 三种模式角标在 UI 上可区分
- [ ] 新队友按前端 README 10 分钟内能启动并走完 S

---

## 八、本冻结明确不做

- 不等待 TEST-R3 / Tool LIVE 才冻结主演示
- 不实现完整比赛 UI
- 不修改 Gateway、Evaluator、Decision Engine、Prompt
- 不把 Mock JSON 升级成后端 Contract
- 不创建空的 `public_artifacts/demo/` 目录；截图有内容后再建

---

_本文档为公开级演示契约，不含内部证据、原始报文或凭据信息。_
