# 当前进展｜CURRENT PROGRESS

> 本文档记录项目从立项到当前阶段的完整时间线。
> **失败历史一律保留，不删除。** 失败记录本身是本项目方法论的一部分。

---

## 时间线总览

```
方案调整
   |
   v
Backend / Evaluator / Decision
   |
   v
腾讯元器迁移
   |
   v
LIVE-1 真实失败
   |
   v
Evidence fail-closed
   |
   v
TEST-P1
   |
   v
LIVE-1R 5/5 PASS
   |
   v
Golden Evidence
   |
   v
P1.4 Tool 验证
   |
   v
FIRST TOOL LIVE
   |
   v
Demo 技术冻结（设计已定，产物待审）
   |
   v
UI / 路演交付冻结（Mock/Replay 控制台）
   |
   v
POC 验证 Agent 收案层
   |
   v
比赛封版
```

---

## 阶段明细

### 1. 方案调整
确定项目定位：不做通用聊天机器人，做 **AI POC 实验验证与技术决策**。
由此确立主链路：需求 / Case → 实验 → Workflow Result → Evaluator → Decision Engine → Comparison。

### 2. Backend / Evaluator / Decision
搭建三件套：
- Backend 负责编排与留痕
- Evaluator 负责独立评估
- Decision Engine 负责输出技术决策结论

确立原则：Evaluator 独立于执行链路，执行方不能自己宣布自己成功。

### 3. 腾讯元器迁移
将 AI 执行能力迁移到腾讯元器平台，Gateway 作为统一出口接管模型 / 工具 / 知识库调用。

### 4. LIVE-1 真实失败（保留）
首次真实端到端实验未通过。
暴露的问题不是"代码写错了"，而是：**证据不足时系统倾向于给出乐观结论。**

这是本项目最有价值的一次失败。它直接推动了下一阶段的核心机制。

### 5. Evidence fail-closed
引入 fail-closed 证据策略：

> 证据不完整、不可读、不可复现时，**一律不允许判定为通过**。

宁可判失败，不可放过没有证据的"看起来成功"。

### 6. TEST-P1
设计核心验证 Case，检验系统能否正确区分：
- 已经证明的事实
- 尚未证明的事实

详见 [`../cases/TEST-P1.md`](../cases/TEST-P1.md)。

### 7. LIVE-1R：5/5 PASS
改进后重跑真实实验，结果：

| 检查项 | 结果 |
| --- | --- |
| HTTP 200 | 5 / 5 |
| Workflow SUCCESS | 5 / 5 |
| Evaluation PASS | 5 / 5 |
| Decision | 全部 `SUPPORT_CONTROLLED_TRIAL` |
| Comparison eligible | true |

关键点：**5/5 通过，不代表生产可用。**
Decision 输出是 `SUPPORT_CONTROLLED_TRIAL`（支持受控试运行），而不是 Production Ready。
系统主动拒绝把结论说过头，这正是它要证明的能力。

### 8. Golden Evidence
建立 Golden Evidence 机制，作为后续评估的对照基准。
（Golden 内部原始证据不进入本公开仓库。）

### 9. P1.4 Tool 验证
进入真实 Tool 能力验证阶段。
目标：从"结果正确"推进到"过程可证明"——拿到真实 Tool Trace，形成完整证据链。

### 10. FIRST TOOL LIVE（进行中）
真实 Tool 首次联调验证。
候选 Case 见 [`../cases/TEST-R3.md`](../cases/TEST-R3.md)。

### 11. Demo 技术冻结（设计已定，产物待审）
已冻结比赛演示契约 `DEMO_FREEZE_v1.0`：固定演示 Case、链路与兜底。
主演示只能是 `DEMO-S` / TEST-P1；TEST-R3 仍是 Tool LIVE 候选，不得作为 3 分钟主线。
现场失败按 LIVE → REPLAY → MOCK 诚实降级，禁止无角标静默切 Mock。

详见 [`../demo/DEMO_FREEZE.md`](../demo/DEMO_FREEZE.md)。
数据包与脚本已落盘。前端已按该契约接入 Mock/Replay；L0 真实运行仍未开放。

### 12. UI / 路演交付冻结（Mock/Replay 已落地）
已实现可点击实验控制台（`frontend/`，`npm run dev`），并冻结路演文案与提交清单 `DELIVERY_FREEZE_v1.0`。
默认加载 DEMO-S 预置回放；`GET /health` 只显示后端在线，**不得**标成真实运行。
这是路演交付包，**不是** Tool LIVE 完成，也不是 `SOURCE_PUBLICATION_REVIEW`。

详见 [`../delivery/DELIVERY_FREEZE.md`](../delivery/DELIVERY_FREEZE.md)、[`../../frontend/README.md`](../../frontend/README.md)。

### 13. POC 验证 Agent 收案层（已落地，非聊天机器人）
后端新增 `POST /api/v1/agent/intake`：把自然语言需求编译成 Formal Case，再交给现有实验流水线。
默认 `planner_source=DETERMINISTIC`；只有配置 `AGENT_LLM_URL` 才调用可选大模型，且模型不得输出 Decision。
前端收案页：`http://127.0.0.1:5173/intake`（需后端与 API_KEY；Fixture 流水线，不是 Tool LIVE）。
这不是 Tool LIVE，也不是生产封版。

详见 [`../agent/POC_VALIDATION_AGENT.md`](../agent/POC_VALIDATION_AGENT.md)。

### 14. 比赛封版（待开始）
比赛版本冻结，执行 `SOURCE_PUBLICATION_REVIEW` 与 `PUBLIC_SOURCE_MIGRATION`，正式源码经安全审核后公开。
Demo 技术冻结与路演交付冻结都不是比赛封版。

---

## 当前状态一句话总结

> 主链路已真实跑通并通过 5/5 验证，结论为**受控试运行**；
> 当前主线是**真实 Tool 能力验证**，目标是让证据从结论级提升到过程级。
> 路演前端为 Mock/Replay 控制台，**不是** Tool LIVE / 生产封版。

---

## 下一步

| 优先级 | 事项 |
| --- | --- |
| P0 | 完成 FIRST TOOL LIVE，取得真实 Tool Trace |
| P0 | 补齐知识库路径证据（TEST-R3） |
| P1 | 建立成本与延迟统一口径 |
| P1 | RealApiAdapter（禁止把 health/Fixture 标成 LIVE） |
| P2 | 比赛封版与源码公开评审 |

---

_本文档为公开级进度说明，不含内部证据、原始报文或凭据信息。_
