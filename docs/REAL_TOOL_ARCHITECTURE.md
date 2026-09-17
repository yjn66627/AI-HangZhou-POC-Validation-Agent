# Real Tool Architecture Reference

> 本文件是团队架构参考资料，不代表 Real Tool 已上线或已完成生产激活。

## 两条链路必须分离

- **Chain A：POC Experiment Execution**：执行实验并产生结构化运行结果。
- **Chain B：Executor Agent Tool Runtime**：由 Executor Agent 通过 Tool Protocol 读取或操作运行时资源。

两条链路的职责、权限和验证结论需要分别维护，不能把 Tool Runtime 的候选实现当成实验执行链的正式替换。

## 首个 Real Tool 方向

首个 Real Tool 面向实验运行结果读取：

```text
GET /api/v1/runs/{run_id}
```

当前 Run Store 为 process-local memory，因此部署时需要 single-worker affinity，直到持久化或共享存储方案另行完成并验证。

## 当前状态

D0 Real Tool Architecture 与 D0W Resource Fact Check 可作为架构参考。Project-native Real Tool Adapter（D1）仍需独立完成 Controller Review、审计和 Windows Apply；本次团队同步不包含 D1 Candidate 实现、临时代码或其证据包。
