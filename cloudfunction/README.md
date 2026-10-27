# CloudBase HTTP 云函数公开示例

这是赛后 P2 云迁移的公开复现候选。已部署版本的业务 handler 来源于 V1.2C；本目录将其 fixture 读取路径改为合成示例，其余 handler 字节保持不变。`server.py` 与 `scf_bootstrap` 来自已部署代码的只读回读，不属于 V1.2C 预部署 ZIP。

线上原版本使用冻结响应。本目录**不包含线上响应数据**，仅提供明确标记为 `SYNTHETIC_DEMO_DATA` 的虚构数据，不能复现或证明实际实验测量结果。Schema、状态码、鉴权与嵌套字段保持兼容。遗留 `tool` 显示字符串和 `source` 标签保持原字面值；`source` 标签不意味着本函数调用 Backend。

## 本地测试

在仓库根目录的独立 Python 环境执行：

```bash
python -m pip install -r cloudfunction/requirements-test.txt
python -m pytest cloudfunction/tests -q
```

本地测试使用临时测试值，不读取真实密钥，不调用腾讯元器、CloudBase 或其他服务。测试覆盖 401、400、404、405、成功 envelope、JSON Schema、嵌套类型、fixture 故障与 fresh-process。

## 请求与响应

`GET /tool/project_experiment_run_read`，`Authorization: Bearer <你自己的测试凭据>`，无 query，客户端不发送 body。参数为零；请求者不能通过 run_id 选择其他实验。未经认证返回 401；不支持的方法返回 405；非空 query 返回 400。业务成功与 fixture 加载错误均用 HTTP 200 envelope 表达，应同时检查 `status`。继承的 handler 忽略 body，并未主动拒绝非空 body。

`contract/TOOL_RESPONSE_DEEP_SCHEMA.json` 描述完整 data 层。合成实验 ID 位于 `output.checks.fictional_experiment_id`；所有示例指标均标为 ESTIMATED、来源为 SYNTHETIC_DEMO_DATA，不是线上测量值。顶层 `latency_ms` 仅为当前 handler 处理耗时。

## 运行方式和边界

函数使用标准库，无第三方运行依赖。部署目录为 `function/`；HTTP 进程监听平台容器内 9000 端口，启动链为 `scf_bootstrap -> server.py -> index.main`。Python3.9 对应已核验部署环境；本轮本地验证使用 Python3.12.14，并未实测新部署或 Python3.9 环境。发布前应核查云厂商当时的运行时支持。

不要将此示例自动接入现有演示链。部署和恢复操作见 [部署说明](deployment/DEPLOYMENT.md) 与 [恢复说明](deployment/ROLLBACK.md)。本目录不含环境 ID、实际域名、凭据、真实数据或线上状态导出。
