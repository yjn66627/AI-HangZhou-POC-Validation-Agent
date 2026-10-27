# 项目公开状态

更新日期：2026-10-26。此页记录公开源码和演示的适用范围，历史设计文档保留其原有日期与署名。

## 2026 年 9 月比赛提交版

包含团队前端控制台、Backend API、Executor Gateway、Tool Runtime、Case Registry、Schema、Evaluator、Decision Engine 和演示主页。受控 Fixture 链路和预置回放用于展示流程，不表示对任意企业数据进行实时测量。

## 赛后 P2 CloudBase 演示

腾讯元器通过 CloudBase HTTP Gateway 调用 Python HTTP 云函数，读取冻结响应。它不实时执行本地 Backend 或任意模型实验。仓库 `cloudfunction/` 提供兼容契约的公开复现实现，使用明确标记为 SYNTHETIC_DEMO_DATA 的虚构数据，不包含线上原始冻结响应或凭据。

## 公开源码验证与限制

- Agent intake 路由复用既有收案服务与运行链；本地回归通过不表示本次已部署到线上。
- 公开安全测试、CloudFunction 契约和前端构建可在独立环境验证；具体命令见 [测试说明](docs/TESTING.md)。
- 完整测试仍有 22 项需要受限评测资源，公开测试显式排除并报告数量；不补入私有答案、不把失败改成通过。
- 任意企业数据接入、通用权限接入、任意模型实时比较及完整商业 SaaS 不属于当前已验证成果。
- 当前仅公开展示，未统一授予通用开源许可；第三方依赖和既有素材分别保留其权利边界。

现行分工见 [README 团队贡献](README.md)；许可与素材说明见 [权利边界](docs/RIGHTS_AND_LICENSING.md)。
