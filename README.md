# AI POC验证与技术决策智能体

**AI-HangZhou-POC-Validation-Agent**

面向企业 AI POC 实验验证、自动评估与技术决策的智能体系统
参赛项目：**AI杭州·超级智能体赛**

在线体验：Coming Soon

---

## 一、30 秒看懂这个项目

**它不是普通聊天机器人。**

普通聊天机器人回答的是"我能不能做这件事"。
这个系统回答的是：

> **"这件事，我们到底证明到了什么程度？能不能上生产？"**

它把一句模糊的需求，变成一条可复核、可追责、可比较的证据链：

```
需求 / Case
    |
    v
Backend             接收需求，编排实验，落库留痕
    |
    v
Gateway             统一出口：模型 / 工具 / 知识库调用
    |
    v
AI Executor         真实执行 Workflow（不是模拟）
    |
    v
Workflow Result     结构化执行结果
    |
    v
Evaluator           独立评估：结果是否达标
    |
    v
Decision Engine     技术决策：支持 / 驳回 / 受控试运行
    |
    v
Comparison          跨 Case、跨版本横向比较
```

核心命题：
**把"AI 项目能不能上线"从人的主观判断，变成机器可复核的证据判定。**

---

## 二、当前真实进展

| 检查项 | 结果 |
| --- | --- |
| LIVE-1R 真实实验 | 已完成 |
| HTTP 200 | 5 / 5 |
| Workflow SUCCESS | 5 / 5 |
| Evaluation PASS | 5 / 5 |
| Decision | 全部 = `SUPPORT_CONTROLLED_TRIAL` |
| Comparison eligible | true |
| 当前阶段 | 进入真实 Tool 验证阶段 |
| UI / Demo 封装 | 尚未完成 |

> ## 重要：`SUPPORT_CONTROLLED_TRIAL` ≠ Production Ready
>
> 当前结论的准确含义是：**集成已证明、质量已达标，可以进入受控试运行。**
>
> 它**不代表**：
> - 真实成本已证明
> - 生产并发已证明
> - 长期稳定性已证明
> - Latency 口径已统一
>
> 请不要对外表述为"已经可以上生产"。
> 严格区分"已证明的事实"和"尚未证明的事实"，就是这个项目的核心能力本身。

---

## 三、仓库导航

| 路径 | 内容 |
| --- | --- |
| [`docs/architecture/PROJECT_ARCHITECTURE.md`](docs/architecture/PROJECT_ARCHITECTURE.md) | 系统架构、模块职责、各模块验证状态 |
| [`docs/progress/CURRENT_PROGRESS.md`](docs/progress/CURRENT_PROGRESS.md) | 完整进展时间线（含失败历史，不删） |
| [`docs/cases/TEST-P1.md`](docs/cases/TEST-P1.md) | 核心 Case：区分"已证明"与"未证明" |
| [`docs/cases/TEST-R3.md`](docs/cases/TEST-R3.md) | 知识库检索异常 Case，首个 Tool 验证候选 |
| [`docs/live/LIVE1R_PUBLIC_SUMMARY.md`](docs/live/LIVE1R_PUBLIC_SUMMARY.md) | LIVE-1R 脱敏公开摘要 |
| [`docs/team/TEAM_ROLES.md`](docs/team/TEAM_ROLES.md) | 团队分工 |
| [`docs/PUBLICATION_POLICY.md`](docs/PUBLICATION_POLICY.md) | 公开边界：什么能公开，什么永远不能 |
| [`public_artifacts/`](public_artifacts/README.md) | 可公开资产（架构图、Demo、UI 素材） |
| [`examples/`](examples/README.md) | 可公开示例 |

协作方式见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

---

## 四、公开边界

本仓库是 **Public**，采用 `PUBLIC_PARTICIPATION_MODE`。
但公开的是**代码与文档**，不是**内部证据与凭据**。

**可以公开**：项目文档、公开 Schema、公开 Formal Case、架构图、当前进度、脱敏 LIVE 摘要、UI / Demo、团队分工、公开 Issue。

**永远不公开**：私有评测答案、密钥类凭据、认证请求头、会话 Cookie、环境变量文件、第三方平台登录信息、未脱敏的原始响应报文、内部原始证据、回滚凭据、浏览器凭据、本机隐私信息、任何真实口令或验证码。

完整规则与提交前自检清单见 [`docs/PUBLICATION_POLICY.md`](docs/PUBLICATION_POLICY.md)。

---

## 五、当前阶段说明：冻结基线已同步

本仓库已同步当前正式冻结基线 `POST_C1D_PRE_REAL_TOOL_WINDOWS_BASELINE` 的可公开源码、Contract、测试与必要配置模板。

同步内容不包含 Private Gold、内部原始证据、真实凭据或机器专用文件。并行开发中的 Project-native Real Tool Adapter（D1）仍处于独立开发 / 审查流程，不属于本次正式团队基线。

---

## 六、团队

| 成员 | 角色 | 职责 |
| --- | --- | --- |
| 小杨 | Project Lead + Experiment Lead | 总体架构、Formal Experiment、Runtime、LIVE、版本治理、最终决策 |
| 小林 | Product / UX / Demo Lead | UI、产品体验、公开 Demo、展示故事线、试玩反馈 |
| 小刘 | Case / QA / Research Support | Case 补充、测试反馈、Bug 复现、Issue、公开资料整理 |

详见 [`docs/team/TEAM_ROLES.md`](docs/team/TEAM_ROLES.md)。

---

## 七、License

本仓库**当前未添加开源 License**。

仓库公开不等于自动授权他人复制、修改、商用。
License 由项目负责人后续单独决定。

---

_本仓库为团队公开协作入口。安全优先，先审计后提交。_
