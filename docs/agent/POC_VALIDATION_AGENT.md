# POC 验证 Agent｜后端设计

> 角色：把自然语言需求收成 Formal Case，并提交现有实验流水线。
> 它不是聊天机器人，也不是 Decision Engine。
> 不修改 Gateway / Evaluator / Decision Engine / 已冻结 Prompt。

---

## 主题对齐

项目问的是：**这件事证明到了什么程度，能不能进入受控试运行？**  
不是：**我能不能做？**

因此 Agent 只做前半段：

```
自然语言需求
    → Intake Planner（编译 Formal Case）
    → 两个候选（系统路径 vs 错误外推 Baseline）
    → 现有 Pipeline（执行 → Evaluator → Decision Engine）
    → 只回传 Decision 档位，禁止 Agent 自己改档位
```

强制边界：

- 不得输出「可以上生产」作为系统结论
- 不得为了让 Evaluator 通过而编造 Evidence
- 成本/延迟用户没给数字时，验收标准标 `NOT_APPLICABLE`，禁止填 0
- 默认 `execution_mode=FIXTURE`；只有 `EXECUTOR_MODE=LIVE` 且显式允许时才 LIVE
- 大模型若未配置，走确定性编译器，并标注 `planner_source=DETERMINISTIC`

---

## 两个角色（一个 Agent，两条职责）

| 角色 | 做什么 | 不做什么 |
| --- | --- | --- |
| Intake Planner | 拆「要证明 / 本次不证明」，生成 task、候选、验收契约 | 不下 Decision |
| Experiment Orchestrator | 把编译结果交给已有 `/api/v1/runs` 流水线 | 不替换 Evaluator |

已有 Gateway Executor Agent 仍只负责「按 spec 执行」。本模块是 **收案层**，挂在 Backend。

---

## 接口

`POST /api/v1/agent/intake`（同样需要 `Authorization: Bearer <API_KEY>`）

请求：

```json
{
  "goal": "我们想用大模型做客服，质量门槛 0.9，还没测成本。能不能上生产？",
  "constraints": ["不允许写操作"],
  "submit": true
}
```

响应含：`case_id`、已证明/未证明列、两个候选摘要、`planner_source`；`submit=true` 时附带 `run_id`，用现有 `GET /api/v1/runs/{id}` 查 Decision。

前端适配页：[`frontend/src/pages/IntakePage.tsx`](../../frontend/src/pages/IntakePage.tsx)，路径 `/intake`。3 分钟主演示仍是 DEMO-S。

调用示例（后端需已配置 `API_KEY`）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/intake ^
  -H "Authorization: Bearer <API_KEY>" ^
  -H "Content-Type: application/json" ^
  -d "{\"goal\":\"我们想用大模型做客服，还没测成本。能不能上生产？\",\"constraints\":[\"不允许写操作\"],\"submit\":true}"
```

Decision 只出现在后续 `GET /api/v1/runs/{run_id}` 里，由独立 Evaluator / Decision Engine 产出。Fixture 下系统路径通常是 `SUPPORT_CONTROLLED_TRIAL`，错误外推 Baseline 不会被推荐为可上线。

可选环境变量（完整清单见 [`docs/ENV.md`](../ENV.md)）：

| 变量 | 含义 |
| --- | --- |
| `AGENT_LLM_URL` | OpenAI 兼容地址。DeepSeek 填 `https://api.deepseek.com` |
| `AGENT_LLM_API_KEY` | DeepSeek API Key；也可使用 `DEEPSEEK_API_KEY`。未填则不调用模型 |
| `AGENT_LLM_MODEL` | 默认 `deepseek-flash` |

LLM 只允许返回收案 JSON，返回里若出现生产上线结论会被丢弃。

---

## 为什么这样放后端

用户要的「输入一个方案判断行不行」入口，应对齐 Formal Case，而不是前端聊天框。  
评估仍独立，执行方不能宣布自己成功。这与 TEST-P1 / LIVE-1R 口径一致。
