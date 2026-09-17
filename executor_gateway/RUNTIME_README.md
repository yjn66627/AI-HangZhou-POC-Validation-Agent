# Executor Gateway Runtime（Deployment-ready，未LIVE验证）

本目录提供独立非冻结Gateway Runtime：

`frozen YuanqiLiveExecutor -> POST /execute -> Gateway -> Compatibility Adapter -> Yuanqi OpenAPI`

当前版本只在沙箱中使用 `httpx.MockTransport` 验证；没有真实访问腾讯元器。

## 运行配置

运行时从环境变量读取：

- `YUANQI_APP_ID`
- `YUANQI_APP_KEY`
- `YUANQI_OPENAPI_URL`
- `EXECUTOR_GATEWAY_API_KEY`
- `YUANQI_HTTP_TIMEOUT_SECONDS`（可选，默认20秒）

缺少必需值时 `/health` 返回503，`/execute` fail closed。

## 运行入口

```bash
uvicorn executor_gateway.app:app --host 127.0.0.1 --port 8010 --workers 1
```

Backend未来配置：

```text
YUANQI_EXECUTOR_URL=http://127.0.0.1:8010/execute
YUANQI_EXECUTOR_API_KEY=<与EXECUTOR_GATEWAY_API_KEY相同>
YUANQI_RESPONSE_MAPPING_FILE=<项目>/adapters/yuanqi_response_mapping_LIVE_GATEWAY.json
```

本文件不包含任何真实Secret。

