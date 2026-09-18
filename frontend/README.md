# 前端实验控制台｜UI_FREEZE_v1.0

比赛路演用 **实验控制台 + 决策报告**，不是聊天机器人。  
数据来自仓库根目录 [`../demo_cases/`](../demo_cases/)，经 MockAdapter 读取。默认角标是 **预置回放**。

`uvicorn backend.app:app` 不是本界面。后端健康检查只显示「后端在线」，**不会**把角标改成「真实运行」。

---

## 10 分钟启动

需要 Node.js 18+。在仓库根目录：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

点「开始 3 分钟（DEMO-S）」走完：需求 → 候选 → 进度 → 对照 → Evidence → Decision。

## 收案页（需后端）

[http://127.0.0.1:5173/intake](http://127.0.0.1:5173/intake) 对接 `POST /api/v1/agent/intake`。Agent 只编译 Formal Case，Decision 仍来自独立引擎。

- 3 分钟路演主线仍是 DEMO-S 预置回放；本页**不是** Tool LIVE / 生产可用
- Vite 把 `/api` 代理到 `127.0.0.1:8000`
- 页面填写的 API_KEY 必须与后端环境变量相同，只留在浏览器会话；可选 `frontend/.env.local` 的 `VITE_API_KEY`，不要提交真实密钥。变量说明见 [`../docs/ENV.md`](../docs/ENV.md)
- 未配置 `AGENT_LLM_URL` 时是确定性编译 + Fixture 流水线

---

## 演示者开场检查单

- [ ] 默认 Case 为 DEMO-S
- [ ] 角标为「预置回放」
- [ ] 浏览器全屏，不要打开 DevTools
- [ ] 不要把 health 在线说成真实实验成功
- [ ] 3 分钟不要切 TEST-R3 / DEMO-U 当主线
- [ ] 口播 Decision 只能说「建议进入受控试运行」

脚本：[`../demo_scripts/SCRIPT_3MIN.md`](../demo_scripts/SCRIPT_3MIN.md)

---

## Mock / Real 切换位置

| 文件 | 作用 |
| --- | --- |
| [`src/adapters/mockAdapter.ts`](src/adapters/mockAdapter.ts) | 当前启用，加载 DEMO-S/N/U/F JSON |
| [`src/adapters/realApiAdapter.ts`](src/adapters/realApiAdapter.ts) | 空壳，禁止当 LIVE 角标来源 |
| [`src/context/DemoContext.tsx`](src/context/DemoContext.tsx) | `REAL_API_ADAPTER_ENABLED` 开关 |
| [`src/adapters/modeGate.ts`](src/adapters/modeGate.ts) | DEMO-S 档位偏离则降 L1；禁止 JSON 自称 L0 |
| [`src/adapters/agentIntake.ts`](src/adapters/agentIntake.ts) | `/intake` 对接后端收案接口；不开启 L0 角标 |

页面只认：`demo_id`、`source_mode`、`case_status`、`candidate_solutions`、`experiment_progress`、`metrics`、`evidence`、`decision`、`warnings`。

---

## 路由

| 路径 | 页面 |
| --- | --- |
| `/` | 首页 |
| `/intake` | POC 验证收案（对接后端 Agent，需 API_KEY；不是 3 分钟主线） |
| `/cases/DEMO-S/requirement` | 需求与约束 |
| `/cases/:id/candidates` | 候选 |
| `/cases/:id/progress` | 进度（可预览运行中） |
| `/cases/:id/comparison` | 对照（NOT_PROVIDED 不画成 0） |
| `/cases/:id/evidence` | Evidence |
| `/cases/:id/decision` | Decision，含 N/U/F 入口 |
| `/cases/:id/exception` | 失败 / 证据不足 |

顶栏「模拟 LIVE 失败」显示冻结口播条，角标保持预置回放。

---

## 未完成项

- RealApiAdapter 尚未把 DEMO-S 数据包换成 `GET /api/v1/runs/{run_id}`
- L0 真实运行角标未开放
- 脱敏截图尚未入库（有内容再建 `public_artifacts/demo/`）
- 未把 dist 挂到 FastAPI，避免改实验后端

`/intake` 已映射 Agent 收案接口，仍不得把 Fixture 结果标成真实运行。

契约：[`../docs/delivery/DELIVERY_FREEZE.md`](../docs/delivery/DELIVERY_FREEZE.md)
