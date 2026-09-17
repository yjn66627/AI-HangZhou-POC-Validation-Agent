# 比赛提交清单｜SUBMISSION

> 对应：`DELIVERY_FREEZE_v1.0`
> 本清单冻结**路演交付包**。它**不是** `SOURCE_PUBLICATION_REVIEW` 完成态，也不是生产封版。

---

## 一、提交物

| 项 | 位置 | 评委怎么用 |
| --- | --- | --- |
| 公开仓库 | 本仓库 README | 看架构、进度、公开 Case |
| 前端 Demo | [`frontend/README.md`](../../frontend/README.md) | `npm install && npm run dev` |
| 3 分钟脚本 | [`demo_scripts/SCRIPT_3MIN.md`](../../demo_scripts/SCRIPT_3MIN.md) | 现场口播 |
| 冻结 Decision 口径 | LIVE-1R：`SUPPORT_CONTROLLED_TRIAL` | 不得说可以上生产 |
| 脱敏进度 | [`docs/progress/CURRENT_PROGRESS.md`](../progress/CURRENT_PROGRESS.md) | 已证明 / 未证明 |
| 路演文案 | [`presentation_assets/PITCH.md`](../../presentation_assets/PITCH.md) | 粘进 PPT |

不要提交：真实 `.env`、Private Gold、未脱敏报文、内网地址、Dify Token、元器登录态。

---

## 二、必须写上的口径

- `SUPPORT_CONTROLLED_TRIAL` ≠ 生产可用。含义是：集成已证明、质量已达标，允许受控试运行。
- 成本、延迟、并发、长期稳定性**尚未证明**。
- TEST-R3 是 Tool LIVE 候选，**不是** 3 分钟主演示。
- 当前前端默认是 **预置回放（L1）**，不是把 Fixture 标成 LIVE。
- Dify 已退出最终技术路线。

---

## 三、公开边界自检

提交 / 演示 / 截图前逐项勾选（规则见 [`../PUBLICATION_POLICY.md`](../PUBLICATION_POLICY.md)）：

- [ ] 不含凭据、令牌、口令、验证码
- [ ] 不含内部原始证据或未脱敏响应报文
- [ ] 不含本机绝对路径
- [ ] 不含个人邮箱、登录账号
- [ ] 不含内部服务地址（可说「本机 5173 / 8000」，不要贴内网域名）
- [ ] 浏览器地址栏、DevTools、控制台已清理后再截图
- [ ] 图中文字与 Decision 档位一致，不出现「可以上生产」作为系统结论

---

## 四、和后续封版的边界

| 事项 | ⑫ 本清单 | 尚未开始 |
| --- | --- | --- |
| 路演 UI / 脚本 / 文案 | 已冻结 | — |
| Tool LIVE / TEST-R3 | 未声称完成 | FIRST TOOL LIVE |
| `SOURCE_PUBLICATION_REVIEW` | 未执行 | 比赛封版阶段 |
| `PUBLIC_SOURCE_MIGRATION` | 未执行 | 比赛封版阶段 |

---

## 五、仓库入口建议对评委说的话

> 打开 README 看 30 秒定位；打开 frontend 走 DEMO-S；结论页写的是受控试运行。5/5 证明的是集成与质量，不是生产就绪。
