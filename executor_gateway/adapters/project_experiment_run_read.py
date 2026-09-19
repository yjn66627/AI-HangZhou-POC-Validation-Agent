from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from executor_gateway.hard_deadline_http import (
    HardDeadlineHttpTransportImpl,
    HardDeadlineResponseTooLarge,
    HardDeadlineTimeout,
    HardDeadlineTransport,
    HardDeadlineTransportError,
)
from executor_gateway.tool_runtime import (
    AdapterExecution,
    CaseResourceBinding,
    ToolError,
    ToolInvocationRequest,
    ToolRuntimeStatus,
)


FORMAL_TOOL_NAME = "实验运行结果读取"
EXECUTABLE_TOOL_ID = "project_experiment_run_read"
ADAPTER_ID = "ProjectExperimentRunReadOnlyAdapter"
ADAPTER_VERSION = "1.0.0-candidate.1"
SOURCE_SYSTEM = "PROJECT_BACKEND_RUN_STORE"
RESOURCE_KIND = "EXPERIMENT_RUN_RESULT_SNAPSHOT"
ASYNC_RUN_STATUSES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED"}
MATERIALIZED_ASYNC_STATUSES = {"COMPLETED", "FAILED"}
_VISIBLE_WORKFLOW_FIELDS = (
    "status",
    "output",
    "quality_metrics",
    "latency",
    "cost",
    "token_usage",
    "errors",
)


def _workflow_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parents[2] / "contracts" / "workflow_result.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


_WORKFLOW_VALIDATOR = _workflow_validator()


@dataclass(frozen=True)
class ProjectExperimentRunAdapterConfig:
    approved_backend_origin: str
    api_credential: str = field(repr=False)
    adapter_id: str = ADAPTER_ID
    adapter_version: str = ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.adapter_id != ADAPTER_ID or self.adapter_version != ADAPTER_VERSION:
            raise ValueError("unapproved_adapter_identity")
        if not self.api_credential or "\n" in self.api_credential or "\r" in self.api_credential:
            raise ValueError("invalid_api_credential")
        origin = self.approved_backend_origin
        if origin != origin.strip() or any(ch.isspace() or ch in {"\\", "%"} for ch in origin):
            raise ValueError("approved_backend_origin_invalid_characters")
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("approved_backend_origin_scheme_not_allowed")
        if not parsed.hostname:
            raise ValueError("approved_backend_origin_host_required")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("approved_backend_origin_userinfo_forbidden")
        if parsed.query or parsed.fragment:
            raise ValueError("approved_backend_origin_query_fragment_forbidden")
        if parsed.path not in {"", "/"}:
            raise ValueError("approved_backend_origin_path_forbidden")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("approved_backend_origin_invalid_port") from exc

        hostname = parsed.hostname
        try:
            hostname.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("approved_backend_origin_host_must_be_ascii") from exc

        host_rendered: str
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            labels = hostname.split(".")
            dns_label = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
            if not labels or any(not dns_label.fullmatch(label) for label in labels):
                raise ValueError("approved_backend_origin_invalid_host")
            host_rendered = hostname.lower()
        else:
            host_rendered = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed

        normalized = f"{parsed.scheme.lower()}://{host_rendered}"
        if port is not None:
            normalized += f":{port}"
        object.__setattr__(self, "approved_backend_origin", normalized)


BACKEND_RUN_ID_PATTERN = re.compile(r"^run-[0-9a-f]{12}$")


def _validate_backend_run_id(value: str) -> str:
    """Validate the exact Backend RUN_STORE key / path identifier without normalization."""
    if not isinstance(value, str) or not value:
        raise ValueError("target_run_id_required")
    if BACKEND_RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("target_run_id_invalid_backend_canonical_form")
    return value


def _failure(
    status: ToolRuntimeStatus,
    code: str,
    *,
    latency_ms: int,
    source_identifier: str = "project-backend-run-snapshot",
) -> AdapterExecution:
    return AdapterExecution(
        status=status,
        data=None,
        error=ToolError(code=code, message=code, retriable=False),
        latency_ms=max(0, latency_ms),
        response_artifact=None,
        source_system=SOURCE_SYSTEM,
        source_identifier=source_identifier,
        auth_scope="READ_ONLY",
    )


def _project_materialized_run(raw: Mapping[str, Any]) -> dict[str, Any]:
    async_status = raw.get("status")
    if not isinstance(async_status, str) or async_status not in ASYNC_RUN_STATUSES:
        raise ValueError("RUN_STATUS_INVALID")
    workflow = raw.get("workflow_result")
    if async_status not in MATERIALIZED_ASYNC_STATUSES or not isinstance(workflow, Mapping):
        raise RuntimeError("RUN_NOT_MATERIALIZED")
    errors = sorted(_WORKFLOW_VALIDATOR.iter_errors(dict(workflow)), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValueError("WORKFLOW_RESULT_SCHEMA_INVALID")

    # Explicit whitelist reconstruction. Nothing outside these fields can flow to the model.
    projected = {"resource_kind": RESOURCE_KIND}
    for key in _VISIBLE_WORKFLOW_FIELDS:
        projected[key] = workflow[key]
    return projected


class ProjectExperimentRunReadOnlyAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        config: ProjectExperimentRunAdapterConfig,
        *,
        transport: HardDeadlineTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or HardDeadlineHttpTransportImpl()

    def invoke(
        self,
        request: ToolInvocationRequest,
        binding: CaseResourceBinding,
        *,
        timeout_ms: int,
        max_response_bytes: int,
    ) -> AdapterExecution:
        if request.executable_tool_id != EXECUTABLE_TOOL_ID:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "WRONG_EXECUTABLE_TOOL", latency_ms=0)
        if request.arguments != {}:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "MODEL_ARGUMENTS_MUST_BE_EMPTY", latency_ms=0)
        if request.case_id != binding.case_id or request.case_binding_id != binding.case_binding_id:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "WRONG_CASE_BINDING", latency_ms=0)
        if binding.source_system != SOURCE_SYSTEM:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "WRONG_BINDING_SOURCE_SYSTEM", latency_ms=0)
        if not binding.read_only:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "BINDING_NOT_READ_ONLY", latency_ms=0)
        if binding.allowed_executable_tools != [EXECUTABLE_TOOL_ID]:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "BINDING_TOOL_SCOPE_INVALID", latency_ms=0)
        if set(binding.resource_refs) != {"target_run_id"}:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "BINDING_RESOURCE_REFS_INVALID", latency_ms=0)
        try:
            run_id = _validate_backend_run_id(binding.resource_refs["target_run_id"])
        except Exception:
            return _failure(ToolRuntimeStatus.SAFETY_BLOCKED, "TARGET_RUN_ID_INVALID", latency_ms=0)

        url = f"{self._config.approved_backend_origin}/api/v1/runs/{run_id}"
        try:
            response = self._transport.get(
                url=url,
                bearer_token=self._config.api_credential,
                timeout_ms=timeout_ms,
                max_response_bytes=max_response_bytes,
            )
        except HardDeadlineTimeout:
            return _failure(ToolRuntimeStatus.TIMEOUT, "TIMEOUT", latency_ms=timeout_ms)
        except HardDeadlineResponseTooLarge:
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "RESPONSE_TOO_LARGE", latency_ms=0)
        except HardDeadlineTransportError:
            return _failure(ToolRuntimeStatus.TOOL_ERROR, "NETWORK_ERROR", latency_ms=0)
        except Exception:
            return _failure(ToolRuntimeStatus.TOOL_ERROR, "TRANSPORT_FAILURE", latency_ms=0)

        status_code = response.status_code
        if 300 <= status_code < 400:
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "REDIRECT_NOT_ALLOWED", latency_ms=response.elapsed_ms)
        if status_code in {401, 403}:
            return _failure(ToolRuntimeStatus.AUTH_ERROR, "AUTH_ERROR", latency_ms=response.elapsed_ms)
        if 400 <= status_code < 500:
            return _failure(ToolRuntimeStatus.HTTP_4XX, "HTTP_4XX", latency_ms=response.elapsed_ms)
        if status_code >= 500:
            return _failure(ToolRuntimeStatus.HTTP_5XX, "HTTP_5XX", latency_ms=response.elapsed_ms)
        if status_code < 200 or status_code >= 300:
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "UNEXPECTED_HTTP_STATUS", latency_ms=response.elapsed_ms)

        try:
            decoded = response.body.decode("utf-8", errors="strict")
            raw = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "MALFORMED_JSON", latency_ms=response.elapsed_ms)
        if not isinstance(raw, Mapping):
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "UNEXPECTED_RESPONSE_SHAPE", latency_ms=response.elapsed_ms)

        try:
            projected = _project_materialized_run(raw)
        except RuntimeError as exc:
            return _failure(ToolRuntimeStatus.TOOL_ERROR, str(exc), latency_ms=response.elapsed_ms)
        except ValueError as exc:
            return _failure(ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, str(exc), latency_ms=response.elapsed_ms)

        return AdapterExecution(
            status=ToolRuntimeStatus.SUCCESS,
            data=projected,
            error=None,
            latency_ms=response.elapsed_ms,
            response_artifact=projected,
            source_system=SOURCE_SYSTEM,
            source_identifier="project-backend-run-snapshot",
            auth_scope="READ_ONLY",
            sensitive_fields_removed=[],
        )
