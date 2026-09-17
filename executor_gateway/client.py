from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .compatibility import (
    CompatibilityConfig,
    ExecuteRequest,
    build_yuanqi_api_request,
    normalize_yuanqi_response,
    validate_platform_model_turn_envelope,
)
from .config import GatewaySettings


class GatewayUpstreamError(RuntimeError):
    category = "UPSTREAM_ERROR"
    http_status = 502

    def __init__(self, message: str, *, upstream_status: int | None = None):
        super().__init__(message)
        self.upstream_status = upstream_status


class GatewayTimeoutError(GatewayUpstreamError):
    category = "UPSTREAM_TIMEOUT"
    http_status = 504


class GatewayConnectionError(GatewayUpstreamError):
    category = "UPSTREAM_CONNECTION_ERROR"
    http_status = 502


class GatewayUpstreamHttpError(GatewayUpstreamError):
    category = "UPSTREAM_HTTP_ERROR"
    http_status = 502


class GatewayUpstreamRateLimited(GatewayUpstreamError):
    category = "UPSTREAM_RATE_LIMITED"
    http_status = 503


class GatewayResponseError(GatewayUpstreamError):
    category = "UPSTREAM_RESPONSE_INVALID"
    http_status = 502


class GatewayModerationBlocked(GatewayResponseError):
    category = "UPSTREAM_MODERATION_BLOCKED"
    http_status = 502


@dataclass(frozen=True)
class GatewayExecutionResult:
    payload: dict[str, Any]
    elapsed_ms: int
    upstream_status: int
    remote_execution_id: str | None


@dataclass(frozen=True)
class GatewayRawHttpResult:
    payload: dict[str, Any]
    elapsed_ms: int
    upstream_status: int


@dataclass(frozen=True)
class GatewayModelCallResult:
    """One validated model-call envelope; never performs Tool orchestration."""

    content: Any
    finish_reason: str
    elapsed_ms: int
    upstream_status: int
    remote_execution_id: str
    native_tool_trace_present: bool


class YuanqiOpenApiClient:
    """Deployment-ready HTTP client。测试必须注入MockTransport；真实运行时transport=None。"""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def _post_json_once(
        self,
        outbound: Mapping[str, Any],
        settings: GatewaySettings,
    ) -> GatewayRawHttpResult:
        """Exactly one HTTP POST. No recursion, polling, replay, or retry-to-pass."""

        headers = {
            "Authorization": f"Bearer {settings.app_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=settings.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(settings.openapi_url, json=dict(outbound), headers=headers)
        except httpx.TimeoutException as exc:
            raise GatewayTimeoutError("yuanqi_upstream_timeout") from exc
        except httpx.RequestError as exc:
            raise GatewayConnectionError(f"yuanqi_upstream_connection_error:{exc.__class__.__name__}") from exc
        elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))

        if response.status_code == 429:
            raise GatewayUpstreamRateLimited("yuanqi_upstream_http_429", upstream_status=429)
        if response.status_code >= 400:
            raise GatewayUpstreamHttpError(
                f"yuanqi_upstream_http_{response.status_code}",
                upstream_status=response.status_code,
            )
        try:
            raw = response.json()
        except Exception as exc:
            raise GatewayResponseError("yuanqi_upstream_non_json") from exc
        if not isinstance(raw, Mapping):
            raise GatewayResponseError("yuanqi_upstream_json_root_must_be_object")
        return GatewayRawHttpResult(
            payload=dict(raw),
            elapsed_ms=elapsed_ms,
            upstream_status=response.status_code,
        )

    async def call_model_once(
        self,
        messages: list[Mapping[str, Any]],
        settings: GatewaySettings,
        *,
        user_id: str = "ai-poc-live-executor",
        custom_variables: Mapping[str, str] | None = None,
    ) -> GatewayModelCallResult:
        """C2 single-call primitive: one POST plus shared platform-envelope safety.

        It deliberately does not parse TOOL_REQUEST/FINAL, invoke tools, count
        rounds, reinject observations, or retry. Those are Orchestrator duties.
        """

        if not isinstance(messages, list) or not messages:
            raise ValueError("model_call_messages_required")
        canonical_messages: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("model_call_message_must_be_object")
            canonical_messages.append(dict(message))
        if not user_id.strip():
            raise ValueError("model_call_user_id_required")
        if custom_variables is not None:
            custom = dict(custom_variables)
            if not all(isinstance(k, str) and k and isinstance(v, str) for k, v in custom.items()):
                raise ValueError("custom_variables_must_be_string_map")
        else:
            custom = None

        outbound: dict[str, Any] = {
            "assistant_id": settings.assistant_id,
            "user_id": user_id,
            "stream": False,
            "messages": canonical_messages,
        }
        if custom is not None:
            outbound["custom_variables"] = custom

        raw = await self._post_json_once(outbound, settings)
        try:
            turn = validate_platform_model_turn_envelope(
                raw.payload,
                allowed_finish_reasons=("stop", "length", "tool_fail", "sensitive"),
            )
        except ValueError as exc:
            detail = str(exc)
            if detail.startswith("yuanqi_moderation_level_"):
                raise GatewayModerationBlocked(f"yuanqi_upstream_model_turn_blocked:{detail}") from exc
            raise GatewayResponseError(f"yuanqi_upstream_model_turn_invalid:{detail}") from exc
        remote_id = raw.payload.get("id")
        if not isinstance(remote_id, str) or not remote_id.strip():
            raise GatewayResponseError("yuanqi_remote_execution_id_missing")
        return GatewayModelCallResult(
            content=turn.message.get("content") if turn.finish_reason == "stop" else None,
            finish_reason=turn.finish_reason,
            elapsed_ms=raw.elapsed_ms,
            upstream_status=raw.upstream_status,
            remote_execution_id=remote_id,
            native_tool_trace_present=turn.native_tool_trace_present,
        )

    async def execute(self, request: ExecuteRequest | Mapping[str, Any], settings: GatewaySettings) -> GatewayExecutionResult:
        """Legacy single-final path. Behavior remains intentionally unchanged."""

        req = request if isinstance(request, ExecuteRequest) else ExecuteRequest.model_validate(request)
        outbound = build_yuanqi_api_request(
            req,
            CompatibilityConfig(
                assistant_id=settings.assistant_id,
                user_id="ai-poc-live-executor",
                environment="UNKNOWN",
            ),
        )
        raw = await self._post_json_once(outbound, settings)
        try:
            normalized = normalize_yuanqi_response(
                raw.payload,
                CompatibilityConfig(
                    assistant_id=settings.assistant_id,
                    user_id="ai-poc-live-executor",
                    environment="UNKNOWN",
                ),
            )
        except Exception as exc:
            raise GatewayResponseError(f"yuanqi_upstream_normalization_failed:{exc}") from exc
        remote_id = normalized.get("meta", {}).get("remote_execution_id")
        return GatewayExecutionResult(
            payload=normalized,
            elapsed_ms=raw.elapsed_ms,
            upstream_status=raw.upstream_status,
            remote_execution_id=None if remote_id is None else str(remote_id),
        )

