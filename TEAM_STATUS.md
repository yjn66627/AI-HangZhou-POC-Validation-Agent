# AI POC 验证与技术决策智能体｜团队协作状态

> 本文件是团队协作文档，不是 Formal Runtime Authority。

## 当前正式基线

`POST_C1D_PRE_REAL_TOOL_WINDOWS_BASELINE`

## 已完成

- POC 实验执行主链
- Gateway / Runtime 基础
- Multi-turn Tool Protocol
- Tool-enabled Prompt Integration
- Prompt Integration Windows Apply
- Offline E2E

## 正在进行

- Project-native Real Tool Adapter
- Hard network deadline
- STAGING Real Tool integration

## 尚未开始

- Prompt production activation
- Tencent Yuanqi real Tool integration
- TEST-R3
- Tool LIVE
- RealApiAdapter / L0 真实运行角标
- `SOURCE_PUBLICATION_REVIEW` 比赛封版

## Demo 技术冻结

- 状态：`DEMO_FREEZE_v1.0` **设计已定，产物待审**
- 契约：[`docs/demo/DEMO_FREEZE.md`](docs/demo/DEMO_FREEZE.md)
- 数据包：[`demo_cases/`](demo_cases/)
- 脚本：[`demo_scripts/`](demo_scripts/)
- 主演示 Case 固定为 `DEMO-S` / TEST-P1；TEST-R3 不得作为 3 分钟主线

## 比赛交付 / 路演冻结

- 状态：`DELIVERY_FREEZE_v1.0` **路演交付包已冻结**
- 契约：[`docs/delivery/DELIVERY_FREEZE.md`](docs/delivery/DELIVERY_FREEZE.md)
- 提交清单：[`docs/delivery/SUBMISSION.md`](docs/delivery/SUBMISSION.md)
- 前端：[`frontend/`](frontend/) Mock/Replay 路演版，`npm run dev` → `http://127.0.0.1:5173`
- 材料：[`presentation_assets/PITCH.md`](presentation_assets/PITCH.md)
- **不是** Tool LIVE 完成，也不是生产封版。默认角标为预置回放，health 200 ≠ 真实运行。

## 团队并行可进行

- 脱敏截图入库（有内容再建 `public_artifacts/demo/`）
- PPT 排版（文案已冻结，勿改 Decision 口径）
- RealApiAdapter（不得把 Fixture 标成 LIVE）

## 路线说明

Dify 已退出最终 Production 路线。D1 Project-native Real Tool Adapter 仍处于独立开发 / 审查流程，本次同步不包含 D1 Candidate、临时代码或未审计产物。

## 公开边界

本仓库为 Public Repository。Private Gold、内部原始证据、真实凭据、未脱敏响应、浏览器会话数据和本机隐私信息不得进入仓库。
