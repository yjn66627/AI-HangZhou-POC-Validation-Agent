from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .client import GatewayUpstreamError, YuanqiOpenApiClient
from .compatibility import ExecuteRequest
from .model_caller import ConfiguredYuanqiModelCaller
from .orchestrator import GatewayMultiTurnOrchestrator, OrchestratorConfig
from .prompt_loader import load_tool_enabled_prompt
from .tool_runtime import ToolRuntimeCore
from .config import GatewayConfigurationError, GatewaySettings, ToolEnabledPromptCandidateConfig

LOGGER = logging.getLogger("executor_gateway.runtime")
SettingsProvider = Callable[[], GatewaySettings]


def _default_settings_provider() -> GatewaySettings:
    return GatewaySettings.from_environ()


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    token = value[len(prefix):].strip()
    return token or None


def build_c2_prompt_integration_candidate(
    *,
    settings: GatewaySettings,
    prompt_config: ToolEnabledPromptCandidateConfig,
    tool_runtime: ToolRuntimeCore,
    outbound_transport: httpx.AsyncBaseTransport | None = None,
) -> GatewayMultiTurnOrchestrator:
    """Explicit OFFLINE candidate construction path; never used by legacy /execute.

    C1B opt-in and hash-gated loading happen before C1C Orchestrator enablement.
    The Tool Runtime is injected by the caller; no production registry/adapter is
    created here. No network request occurs during construction.
    """

    loaded_prompt = load_tool_enabled_prompt(prompt_config)
    client = YuanqiOpenApiClient(transport=outbound_transport)
    model_caller = ConfiguredYuanqiModelCaller(client=client, settings=settings)
    return GatewayMultiTurnOrchestrator(
        model_caller=model_caller,
        tool_runtime=tool_runtime,
        config=OrchestratorConfig.for_c1c_tool_enabled_prompt(),
        loaded_prompt=loaded_prompt,
    )


def create_app(
    *,
    settings_provider: SettingsProvider | None = None,
    outbound_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    provider = settings_provider or _default_settings_provider
    client = YuanqiOpenApiClient(transport=outbound_transport)
    app = FastAPI(title="AI POC Executor Gateway", version="1.2.6-candidate")

    def load_settings() -> GatewaySettings:
        try:
            return provider()
        except GatewayConfigurationError as exc:
            raise HTTPException(status_code=503, detail={"code": "GATEWAY_NOT_CONFIGURED", "message": str(exc)}) from exc

    @app.get("/health")
    async def health():
        try:
            settings = provider()
        except GatewayConfigurationError:
            return JSONResponse(status_code=503, content={"status": "NOT_READY", "configured": False, "secrets_exposed": False})
        return {"status": "OK", **settings.safe_summary()}

    @app.post("/execute")
    async def execute(payload: ExecuteRequest, authorization: str | None = Header(default=None)):
        settings = load_settings()
        token = _bearer_token(authorization)
        if token is None or not hmac.compare_digest(token, settings.gateway_api_key):
            LOGGER.warning("gateway_auth_rejected run_id=%s", payload.run_id)
            raise HTTPException(status_code=401, detail={"code": "GATEWAY_UNAUTHORIZED"})
        try:
            result = await client.execute(payload, settings)
        except GatewayUpstreamError as exc:
            LOGGER.warning(
                "gateway_execute_failed run_id=%s category=%s upstream_status=%s",
                payload.run_id,
                exc.category,
                exc.upstream_status,
            )
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "error": {
                        "code": exc.category,
                        "upstream_status": exc.upstream_status,
                        "message": str(exc),
                    }
                },
            )
        LOGGER.info(
            "gateway_execute_completed run_id=%s upstream_status=%s remote_execution_id=%s elapsed_ms=%s",
            payload.run_id,
            result.upstream_status,
            result.remote_execution_id,
            result.elapsed_ms,
        )
        return result.payload

    return app


# Uvicorn部署入口。导入模块时不读取环境变量；配置在health/execute请求时fail closed加载。
app = create_app()

