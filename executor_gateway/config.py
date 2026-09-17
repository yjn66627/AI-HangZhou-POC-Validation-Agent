from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


class GatewayConfigurationError(ValueError):
    """运行时配置缺失或无效；必须fail closed。"""


_PLACEHOLDER_MARKERS = {"<PLACEHOLDER_ONLY>", "PLACEHOLDER", "CHANGEME", "YOUR_VALUE_HERE"}


def _required(source: Mapping[str, str], name: str) -> str:
    value = str(source.get(name, "") or "").strip()
    if not value or value.upper() in _PLACEHOLDER_MARKERS:
        raise GatewayConfigurationError(f"missing_required_config:{name}")
    return value


@dataclass(frozen=True)
class GatewaySettings:
    assistant_id: str
    app_key: str
    openapi_url: str
    gateway_api_key: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "GatewaySettings":
        source = os.environ if environ is None else environ
        assistant_id = _required(source, "YUANQI_APP_ID")
        app_key = _required(source, "YUANQI_APP_KEY")
        openapi_url = _required(source, "YUANQI_OPENAPI_URL")
        gateway_api_key = _required(source, "EXECUTOR_GATEWAY_API_KEY")
        parsed = urlparse(openapi_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GatewayConfigurationError("invalid_config:YUANQI_OPENAPI_URL")
        raw_timeout = str(source.get("YUANQI_HTTP_TIMEOUT_SECONDS", "") or "").strip()
        try:
            timeout_seconds = 20.0 if not raw_timeout else float(raw_timeout)
        except ValueError as exc:
            raise GatewayConfigurationError("invalid_config:YUANQI_HTTP_TIMEOUT_SECONDS") from exc
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise GatewayConfigurationError("invalid_config:YUANQI_HTTP_TIMEOUT_SECONDS")
        return cls(
            assistant_id=assistant_id,
            app_key=app_key,
            openapi_url=openapi_url,
            gateway_api_key=gateway_api_key,
            timeout_seconds=timeout_seconds,
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "configured": True,
            "timeout_seconds": self.timeout_seconds,
            "secrets_exposed": False,
        }



APPROVED_TOOL_ENABLED_PROMPT_VERSION = "C2_TOOL_ENABLED_CANDIDATE_r1"
APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH = (
    "executor_gateway/prompt_assets/"
    "EXECUTOR_AGENT_SYSTEM_PROMPT_C2_TOOL_ENABLED_CANDIDATE_r1.md"
)
APPROVED_TOOL_ENABLED_PROMPT_SHA256 = "c8cfbe65182a226704366727e39af14f2247c4d0b9e9992cbc554e9fcef84682"
_TOOL_ENABLED_PROMPT_ENABLE_ENV = "EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED"
_TOOL_ENABLED_PROMPT_VERSION_ENV = "EXECUTOR_TOOL_ENABLED_PROMPT_VERSION"
_TOOL_ENABLED_PROMPT_PATH_ENV = "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH"
_TOOL_ENABLED_PROMPT_SHA_ENV = "EXECUTOR_TOOL_ENABLED_PROMPT_SHA256"


def _strict_bool(source: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = str(source.get(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise GatewayConfigurationError(f"invalid_config:{name}")


@dataclass(frozen=True)
class ToolEnabledPromptCandidateConfig:
    """Fail-closed binding for the one controller-approved C1A Prompt asset."""

    enabled: bool = False
    version: str = APPROVED_TOOL_ENABLED_PROMPT_VERSION
    logical_path: str = APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH
    expected_sha256: str = APPROVED_TOOL_ENABLED_PROMPT_SHA256

    def __post_init__(self) -> None:
        if self.version != APPROVED_TOOL_ENABLED_PROMPT_VERSION:
            raise GatewayConfigurationError("unapproved_tool_enabled_prompt_version")
        if self.logical_path != APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH:
            raise GatewayConfigurationError("unapproved_tool_enabled_prompt_logical_path")
        if self.expected_sha256 != APPROVED_TOOL_ENABLED_PROMPT_SHA256:
            raise GatewayConfigurationError("unapproved_tool_enabled_prompt_sha256")

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ToolEnabledPromptCandidateConfig":
        source = os.environ if environ is None else environ
        enabled = _strict_bool(source, _TOOL_ENABLED_PROMPT_ENABLE_ENV, default=False)
        version = str(
            source.get(_TOOL_ENABLED_PROMPT_VERSION_ENV, APPROVED_TOOL_ENABLED_PROMPT_VERSION)
            or ""
        ).strip()
        logical_path = str(
            source.get(_TOOL_ENABLED_PROMPT_PATH_ENV, APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH)
            or ""
        ).strip()
        expected_sha256 = str(
            source.get(_TOOL_ENABLED_PROMPT_SHA_ENV, APPROVED_TOOL_ENABLED_PROMPT_SHA256)
            or ""
        ).strip().lower()
        return cls(
            enabled=enabled,
            version=version,
            logical_path=logical_path,
            expected_sha256=expected_sha256,
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "version": self.version,
            "logical_path": self.logical_path,
            "expected_sha256": self.expected_sha256,
            "fallback_allowed": False,
        }
