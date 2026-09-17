# 比赛交付冻结｜DELIVERY FREEZE

> 版本：`DELIVERY_FREEZE_v1.0`
> 状态：路演交付包已冻结；不是 Tool LIVE 完成，也不是 `SOURCE_PUBLICATION_REVIEW`
> 钉死上游：`DEMO_FREEZE_v1.0` + `UI_FREEZE_v1.0`
> 冻结权：小杨
> UI / 故事线：小林
> Case / QA：小刘
>
> 不修改 Gateway / Runtime / Prompt / Evaluator / Decision Engine。

---

## 一、⑫ 冻结什么

⑪ 冻结的是演示技术契约（Case / 链路 / 兜底）。  
⑫ 把四件**对外交付物**锁成同一版本，现场不得各改各的。

| 轴 | 冻结物 | 版本 |
| --- | --- | --- |
| UI | [`frontend/`](../../frontend/) 实验控制台，默认 L1 回放 | `UI_FREEZE_v1.0` |
| 材料 | [`presentation_assets/PITCH.md`](../../presentation_assets/PITCH.md) | 随本版本 |
| 演示 | [`demo_scripts/`](../../demo_scripts/) 与前端一键入口对齐 | 随 `DEMO_FREEZE_v1.0` |
| 提交 | [`SUBMISSION.md`](SUBMISSION.md) 公开边界与提交清单 | 随本版本 |

改其中任何一轴（页面文案、Decision 译法、主 Case、角标规则、路演金句）必须升到 `DELIVERY_FREEZE_vN+1`，并同步改脚本与数据包。禁止只改 UI 不改 Decision。

本冻结不是：

- 腾讯元器真实 Tool LIVE 已通过
- 可以对外说「生产可用」
- 源码公开评审完成
- 把 `demo_cases` JSON 升级成后端 Contract

---

## 二、UI 冻结（UI_FREEZE_v1.0）

启动：`cd frontend && npm install && npm run dev` → `http://127.0.0.1:5173`  
`uvicorn backend.app:app` 仍是实验 API，**不是**本控制台。`GET /health` 200 只显示「后端在线」，**不得**把角标改成「真实运行」。

| 路由 | 页面 |
| --- | --- |
| `/` | 首页 |
| `/cases/:id/requirement` | 需求与约束 |
| `/cases/:id/candidates` | 候选方案 |
| `/cases/:id/progress` | 实验进度 |
| `/cases/:id/comparison` | 对照结果 |
| `/cases/:id/evidence` | Evidence |
| `/cases/:id/decision` | Decision |
| `/cases/:id/exception` | 失败 / 证据不足 |

默认 Case：`DEMO-S`。默认 `source_mode`：`L1_REPLAY`，角标「预置回放」。  
Adapter 只认展示层字段；页面不直连 Contract。RealApiAdapter 仅为空壳。

Decision 展示用语不得改写：

| result | code |
| --- | --- |
| 建议进入受控试运行 | `SUPPORT_CONTROLLED_TRIAL` |
| 暂缓，不进入推荐 | `DEFER` |
| 证据不足，继续验证 | `INSUFFICIENT_EVIDENCE` |
| 运行未完整成功，需人工辅助 | `HUMAN_ASSISTED` |
| 安全阻断 | `BLOCKED_BY_SAFETY` |

DEMO-S 若拿到其它 `code`，ModeGate 必须降为 L1 并改角标。  
「模拟 LIVE 失败」只改角标与口播条，不把 Fixture 标成 LIVE。

---

## 三、材料冻结

路演金句锁定（三选一里**只用这一句**）：

> 它不是普通聊天机器人。它回答的是：这件事到底证明到了什么程度，能不能上生产。

完整幻灯片文案、流程/架构节点、四列对比、截图位见 [`../../presentation_assets/PITCH.md`](../../presentation_assets/PITCH.md)。  
不提交 `.pptx` 二进制。脱敏截图有内容后再建 `public_artifacts/demo/`。

---

## 四、演示冻结

| 时长 | 前端路径 | 脚本 |
| --- | --- | --- |
| 3 分钟 | 首页「开始 3 分钟」→ 只走 `DEMO-S`，停在对照 + Decision | [`../../demo_scripts/SCRIPT_3MIN.md`](../../demo_scripts/SCRIPT_3MIN.md) |
| 5 分钟 | Decision 页切换 N 或 U；F 一键待命 | [`../../demo_scripts/SCRIPT_5MIN.md`](../../demo_scripts/SCRIPT_5MIN.md) |
| 故障 | 顶栏「模拟 LIVE 失败」 | [`../../demo_scripts/FAILOVER.md`](../../demo_scripts/FAILOVER.md) |

TEST-R3 不得作为 3 分钟主线。

---

## 五、提交冻结

见 [`SUBMISSION.md`](SUBMISSION.md)。⑫ 冻结的是路演交付包，不是比赛源码公开评审完成。

---

## 六、验收

- [x] 四轴版本钉在 `DELIVERY_FREEZE_v1.0`
- [x] 前端可 `npm run dev` 走完 DEMO-S 八类页面
- [x] 角标可区分；health 200 不变成真实运行
- [x] 路演文案与 Decision 口径一致，不出现「可以上生产」作为系统结论
- [x] 提交清单含公开边界自检
- [ ] 脱敏截图入库（有图再建目录）
- [ ] RealApiAdapter 接入真实 TEST-P1（非本版本）

---

_本文档为公开级路演契约，不含内部证据、原始报文或凭据信息。_
