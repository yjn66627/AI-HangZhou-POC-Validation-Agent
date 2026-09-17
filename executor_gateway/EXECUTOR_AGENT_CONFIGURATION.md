# Executor Agent 配置草案｜离线候选

状态：`TEMPLATE_ONLY / NOT_LIVE_VERIFIED`

本文件只描述未来真实环境需要配置的项目，不创建、不发布、不调用真实腾讯元器智能体。

## 未来配置项

- `assistant_id`：由真实平台环境提供；本轮测试只使用 `<PLACEHOLDER_ASSISTANT_ID>`。
- `user_id`：建议使用稳定、非个人敏感的执行器标识。
- `stream`：固定为 `false`。
- `messages`：由 `build_yuanqi_api_request()` 生成，正文是完整 `{run_id, task, candidate, experiment_spec}` JSON字符串。
- `custom_variables`：可选；仅允许字符串键和值。本轮不依赖它。

## 输出约束

系统提示词使用 `EXECUTOR_AGENT_SYSTEM_PROMPT.md`；最终消息内容必须是严格JSON并通过 `EXECUTOR_AGENT_OUTPUT_CONTRACT.schema.json`。

平台指标不由Agent生成：Token、Latency、Cost、remote execution id、Tool Trace必须来自平台响应；缺失时保持未知/NOT_PROVIDED语义。
