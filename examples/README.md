# examples｜可公开示例

本目录存放**可公开的运行示例**，用于说明如何调用与使用本项目的能力。

---

## 一、目录用途

- 演示典型 Case 的输入形式
- 演示公开 Schema 的使用方式
- 提供最小可运行示例

---

## 二、准入规则

- [ ] 示例中的**全部**密钥类字段使用假值
- [ ] 示例地址一律使用占位域名，不使用真实服务地址
- [ ] 不含内部原始证据
- [ ] 不含本机绝对路径
- [ ] 不含真实业务数据

详见 [`../docs/PUBLICATION_POLICY.md`](../docs/PUBLICATION_POLICY.md)。

---

## 三、示例配置的写法

如果示例需要配置文件，请提交 `.env.example`（**已被 `.gitignore` 白名单放行**），且全部使用假值：

```
# 全部为尖括号占位符，请勿填入真实凭据
变量名=<在此填写你自己的值>
服务地址=<在此填写你自己的地址>
```

**不得提交**真实的 `.env` 文件。

---

## 四、建议结构

```
examples/
├── basic/            最小示例
├── case-inputs/      典型 Case 输入样例
└── schema/           公开 Schema 使用示例
```

子目录在**首次有实际内容时**再创建。

---

## 五、当前状态

已恢复 5 个历史 sandbox bundle 与 1 个元器请求模板，并逐文件核对历史归档和冻结测试资源清单。它们是可公开的受控模拟输入，不是实际企业测量结果。

`fx-*_bundle.json` 保留 `SANDBOX_FIXTURE_ONLY` 标记；`yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json` 只说明请求协议，测试执行器使用 stub/mock。`datasets/fixture_inputs.json` 的 5 行执行器可见输入也已与这些 bundle 的 Task 逐字段匹配，不含预期答案字段。

赛后 CloudBase 的新合成响应位于 `cloudfunction/function/fixtures/synthetic_demo_success.json`，明确标记为 `SYNTHETIC_DEMO_DATA`，不包含线上冻结响应。
参见 [`../docs/architecture/PROJECT_ARCHITECTURE.md`](../docs/architecture/PROJECT_ARCHITECTURE.md) 了解当前阶段。

---

_示例必须能被他人在无内部资源的情况下看懂。_
