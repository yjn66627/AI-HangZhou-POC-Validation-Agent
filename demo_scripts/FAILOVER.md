# 演示兜底口播｜FAILOVER

> 规则原文见 [`../docs/demo/DEMO_FREEZE.md`](../docs/demo/DEMO_FREEZE.md) 第三节。
> 现场只允许 L0 → L1 → L2 → 静态截图，禁止无角标静默切 Mock。

---

## 一、开场前 60 秒（评委未入座）

1. 打开 Demo 控制台。
2. 对 `DEMO-S` 做一次 health + smoke。
3. 判定：

| 结果 | 开场模式 | 角标 |
| --- | --- | --- |
| health 通过，且 Decision 为 `SUPPORT_CONTROLLED_TRIAL` | L0 LIVE | 真实运行 |
| health 失败、超时、5xx，或 Decision 偏离 | L1 REPLAY（加载 `demo_cases/DEMO-S.json`） | 预置回放 |
| 回放包无法加载 | L2 MOCK（仍是同一 JSON，只改角标） | 演示数据 |

评委面前**不重试超过一次**。第一次失败就停留在 L1，不要反复刷新。

---

## 二、演示中 LIVE 失败

触发：超时、5xx、tool_fail、Decision 不是 `SUPPORT_CONTROLLED_TRIAL`。

操作：立刻加载 `DEMO-S.json`，角标从「真实运行」改为「预置回放」。不要解释堆栈。

口播（约 12 秒，可插入对照段或 Decision 段开头）：

> 现场链路当前不稳定，我们切换到已冻结的同一 Case 回放。结论口径与 LIVE-1R 公开结果一致：5/5 通过，档位是受控试运行，不是生产可用。

禁止说：

- 「刚才其实也跑通了」
- 「Mock 一下不影响」
- 「系统出了点小问题，但结果是可以上生产的」

若 L1 也打不开：改角标为「演示数据」，口播改为：

> 回放包暂时无法加载，当前是演示数据，字段和冻结 Decision 仍然一致。

若投影 / 浏览器全挂：打开预先导出的对照页与 Decision 页脱敏截图（待 `public_artifacts/demo/` 有内容后使用），口播：

> 这是静态截图，不是现场运行。结论仍是受控试运行。

---

## 三、需要展示失败能力时（DEMO-F）

点击：一键打开 `DEMO-F`，进入页面 8。

口播：

> 工具失败或超时不会被当成成功。系统给出人工辅助档位，并停止继续调工具。失败也要有 Final，这是 fail-closed，不是事故现场。

评委应看到：`HUMAN_ASSISTED`；进度在对照实验失败；质量分为未提供。

---

## 四、DEMO-S 档位偏离的判定

只有以下组合算 L0 成功：

- HTTP 200 口径可公开叙述为 5/5
- Workflow SUCCESS
- Evaluation PASS
- Decision 全部为 `SUPPORT_CONTROLLED_TRIAL`

其它任何 Decision（`DEFER`、`HUMAN_ASSISTED`、`INSUFFICIENT_EVIDENCE`、`BLOCKED_BY_SAFETY`）在 `DEMO-S` 现场都算演示事故，切 L1，不要把事故 Case 即兴讲成主线。
