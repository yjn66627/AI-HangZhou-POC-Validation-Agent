# 腾讯元器 Adapter（适配器）v1.2

`POST /api/v1/yuanqi/runs` 已真实调用 `prepare_run_requests()`，腾讯元器前半段无需自行拼内部复杂Schema。

默认模板仍标记 `TEMPLATE_NOT_LIVE_VERIFIED`，**不代表腾讯元器官方JSON格式**。真实字段必须由Codex拿到脱敏真实payload后校准。

v1.2已实现：
- 严格布尔解析：`"false"`→False；非法字符串报错；
- `experiment_id`、`required_tools`、candidate-specific tools实际读取；
- 缺失远端started/finished时间时写null + `NOT_PROVIDED`，本地仅另记`received_at`；
- environment由payload/映射提供，未知为`UNKNOWN`，不硬编码STAGING；
- 平台提供remote execution id时单独映射，绝不用本地run_id冒充；
- 未提供的Cost/Latency/Token合法表达为`NOT_PROVIDED`；
- 未知字段不会渗透到核心业务逻辑。
