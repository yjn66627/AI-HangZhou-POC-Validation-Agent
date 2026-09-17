from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TOOL_CALL_ID_RE = re.compile(r"^tc_[0-9a-f]{32}$")
AUDIT_EVENT_ID_RE = re.compile(r"^ta_[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EXECUTABLE_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

_CREDENTIAL_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "x_api_key",
    "access_token",
    "refresh_token",
    "bearer_token",
    "token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "credential",
    "credentials",
    "cookie",
    "set_cookie",
}
_URL_KEYS = {"url", "base_url", "host", "hostname", "endpoint", "endpoint_url"}
_RESOURCE_ID_KEYS = {
    "resource_id",
    "knowledge_base_id",
    "dataset_id",
    "workflow_id",
    "document_id",
    "app_id",
    "tenant_id",
}
_URL_VALUE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{6,}"),
    re.compile(r"(?i)\bsk-(?:proj-)?[A-Za-z0-9_-]{6,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|authorization)\s*[:=]\s*[^\s,;]+"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_artifact(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _key_kind(key: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    if normalized in _CREDENTIAL_KEYS:
        return "CREDENTIAL_FIELD_FORBIDDEN"
    if normalized in _URL_KEYS:
        return "ARBITRARY_URL"
    if normalized in _RESOURCE_ID_KEYS:
        return "ARBITRARY_RESOURCE_ID"
    return None


def _contains_credential_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in _CREDENTIAL_VALUE_PATTERNS)


def _walk_values(value: Any, *, path: str = "") -> list[tuple[str, str, Any]]:
    findings: list[tuple[str, str, Any]] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            kind = _key_kind(key)
            if kind:
                findings.append((kind, child_path, child))
            findings.extend(_walk_values(child, path=child_path))
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            findings.extend(_walk_values(child, path=f"{path}[{idx}]"))
    elif isinstance(value, str):
        if _contains_credential_like_value(value):
            findings.append(("CREDENTIAL_LIKE_ARGUMENT_BLOCKED", path or "$", value))
        elif _URL_VALUE_RE.match(value.strip()):
            findings.append(("ARBITRARY_URL", path or "$", value))
    return findings


def _sanitize_recursive(value: Any) -> tuple[Any, list[str]]:
    removed: list[str] = []

    def rec(node: Any, path: str) -> Any:
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for raw_key, child in node.items():
                key = str(raw_key)
                child_path = f"{path}.{key}" if path else key
                if _key_kind(key) == "CREDENTIAL_FIELD_FORBIDDEN":
                    out[key] = "[REDACTED]"
                    removed.append(child_path)
                else:
                    out[key] = rec(child, child_path)
            return out
        if isinstance(node, (list, tuple)):
            return [rec(child, f"{path}[{idx}]") for idx, child in enumerate(node)]
        if isinstance(node, str) and _contains_credential_like_value(node):
            removed.append(path or "$")
            return "[REDACTED]"
        return node

    return rec(value, ""), sorted(set(removed))


def sanitize_for_audit(value: Any) -> tuple[Any, list[str]]:
    """Sanitize canonical persisted/hashable audit material before persistence."""

    return _sanitize_recursive(value)


def sanitize_for_model_observation(value: Any) -> tuple[Any, list[str]]:
    """Independent safety boundary for any object that may be re-injected to a model."""

    return _sanitize_recursive(value)


class ToolRuntimeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    AUTH_ERROR = "AUTH_ERROR"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    TOOL_ERROR = "TOOL_ERROR"
    RESPONSE_VALIDATION_ERROR = "RESPONSE_VALIDATION_ERROR"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"


class BlockedReason(str, Enum):
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    PROHIBITED_TOOL = "PROHIBITED_TOOL"
    ARBITRARY_URL = "ARBITRARY_URL"
    ARBITRARY_RESOURCE_ID = "ARBITRARY_RESOURCE_ID"
    CREDENTIAL_FIELD_FORBIDDEN = "CREDENTIAL_FIELD_FORBIDDEN"
    CREDENTIAL_LIKE_ARGUMENT_BLOCKED = "CREDENTIAL_LIKE_ARGUMENT_BLOCKED"
    NON_READ_ONLY_OPERATION = "NON_READ_ONLY_OPERATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    WRONG_CASE_BINDING = "WRONG_CASE_BINDING"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    REQUEST_SEQUENCE_INVALID = "REQUEST_SEQUENCE_INVALID"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    REGISTRY_DISABLED = "REGISTRY_DISABLED"
    CASE_NOT_ALLOWED = "CASE_NOT_ALLOWED"
    EXPERIMENT_NOT_ALLOWED = "EXPERIMENT_NOT_ALLOWED"
    CANDIDATE_NOT_ALLOWED = "CANDIDATE_NOT_ALLOWED"


class BlockedStage(str, Enum):
    TOOL_REQUEST_PARSER = "TOOL_REQUEST_PARSER"
    INVOCATION_GUARD = "INVOCATION_GUARD"


class SanitizationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credentials_removed: bool = True
    sensitive_fields_removed: list[str] = Field(default_factory=list)


class ModelToolIntent(BaseModel):
    """Programmatic input contract for C1. C2 will decide how the LLM emits it."""

    model_config = ConfigDict(extra="forbid")
    turn_type: str = "TOOL_REQUEST"
    requested_tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    request_sequence: int = Field(ge=1)
    model_message_ref: str = Field(min_length=1, max_length=256)

    @field_validator("turn_type")
    @classmethod
    def _turn_type(cls, value: str) -> str:
        if value != "TOOL_REQUEST":
            raise ValueError("turn_type_must_be_TOOL_REQUEST")
        return value


class ToolInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lifecycle_stage: str = "PRE_GUARD_CANDIDATE"
    run_id: str = Field(min_length=1)
    repeat_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    requested_tool: str = Field(min_length=1, max_length=128)
    executable_tool_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    arguments: dict[str, Any]
    request_sequence: int = Field(ge=1)
    model_message_ref: str = Field(min_length=1)
    case_binding_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _stage(self) -> "ToolInvocationRequest":
        if self.lifecycle_stage != "PRE_GUARD_CANDIDATE":
            raise ValueError("invalid_invocation_lifecycle_stage")
        return self


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1)
    message: str = ""
    retriable: bool = False


class ToolProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    auth_scope: str = "READ_ONLY"
    request_artifact_sha256: str
    response_artifact_sha256: str | None = None

    @field_validator("request_artifact_sha256")
    @classmethod
    def _request_hash(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("invalid_request_artifact_sha256")
        return value

    @field_validator("response_artifact_sha256")
    @classmethod
    def _response_hash(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_RE.fullmatch(value):
            raise ValueError("invalid_response_artifact_sha256")
        return value

    @field_validator("auth_scope")
    @classmethod
    def _read_only_scope(cls, value: str) -> str:
        if value != "READ_ONLY":
            raise ValueError("auth_scope_must_be_READ_ONLY")
        return value


class ToolResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lifecycle_stage: str = "POST_GUARD_EXECUTION"
    tool_call_id: str
    tool: str = Field(min_length=1)
    executable_tool_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    status: ToolRuntimeStatus
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    latency_ms: int = Field(ge=0)
    attempt: int = Field(default=1, ge=1)
    provenance: ToolProvenance
    sanitization: SanitizationState
    audit_artifact_sha256: str

    @field_validator("tool_call_id")
    @classmethod
    def _tc_namespace(cls, value: str) -> str:
        if not TOOL_CALL_ID_RE.fullmatch(value):
            raise ValueError("tool_call_id_must_use_tc_namespace")
        return value

    @field_validator("audit_artifact_sha256")
    @classmethod
    def _audit_hash(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("invalid_audit_artifact_sha256")
        return value

    @model_validator(mode="after")
    def _status_consistency(self) -> "ToolResultEnvelope":
        if self.lifecycle_stage != "POST_GUARD_EXECUTION":
            raise ValueError("invalid_result_lifecycle_stage")
        if self.status == ToolRuntimeStatus.SUCCESS and self.error is not None:
            raise ValueError("success_result_must_not_have_error")
        if self.status != ToolRuntimeStatus.SUCCESS and self.error is None:
            raise ValueError("failure_result_requires_error")
        if self.status == ToolRuntimeStatus.SUCCESS and self.provenance.response_artifact_sha256 is None:
            raise ValueError("success_requires_response_artifact")
        return self


class BlockedInvocationAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_event_id: str
    run_id: str = Field(min_length=1)
    repeat_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    requested_tool: str = Field(min_length=1, max_length=128)
    sanitized_arguments: dict[str, Any]
    request_sequence: int = Field(ge=1)
    model_message_ref: str = Field(min_length=1)
    blocked_reason: BlockedReason
    blocked_stage: BlockedStage
    created_at: str = Field(min_length=1)
    external_call_started: bool = False
    evidence_eligible: bool = False
    sanitization: SanitizationState
    artifact_sha256: str

    @field_validator("audit_event_id")
    @classmethod
    def _ta_namespace(cls, value: str) -> str:
        if not AUDIT_EVENT_ID_RE.fullmatch(value):
            raise ValueError("audit_event_id_must_use_ta_namespace")
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def _artifact_hash(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("invalid_blocked_artifact_sha256")
        return value

    @model_validator(mode="after")
    def _blocked_constants(self) -> "BlockedInvocationAuditEvent":
        if self.external_call_started:
            raise ValueError("blocked_event_cannot_start_external_call")
        if self.evidence_eligible:
            raise ValueError("blocked_event_cannot_be_evidence_eligible")
        return self


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formal_tool_name: str = Field(min_length=1)
    formal_capabilities: list[str] = Field(min_length=1)
    executable_tool_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    side_effect_class: SideEffectClass
    argument_schema: dict[str, Any]
    allowed_methods: list[str] = Field(default_factory=list)
    allowed_cases: list[str] = Field(min_length=1)
    enabled: bool = False

    @field_validator("formal_capabilities")
    @classmethod
    def _unique_capabilities(cls, value: list[str]) -> list[str]:
        if not value or len(value) != len(set(value)):
            raise ValueError("formal_capabilities_must_be_unique_nonempty")
        return value

    @field_validator("allowed_methods")
    @classmethod
    def _upper_methods(cls, value: list[str]) -> list[str]:
        return [str(x).upper() for x in value]

    @model_validator(mode="after")
    def _formal_primary_is_capability(self) -> "ToolSpec":
        if self.formal_tool_name not in self.formal_capabilities:
            raise ValueError("formal_tool_name_must_be_in_capabilities")
        Draft202012Validator.check_schema(self.argument_schema)
        return self


class CaseResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_binding_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    environment: str = "CONTROLLED_TEST"
    source_system: str = Field(min_length=1)
    allowed_executable_tools: list[str] = Field(default_factory=list)
    resource_refs: dict[str, str] = Field(default_factory=dict)
    read_only: bool = True
    binding_version: str = Field(min_length=1)
    created_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _binding_constants(self) -> "CaseResourceBinding":
        if self.environment != "CONTROLLED_TEST":
            raise ValueError("binding_environment_must_be_CONTROLLED_TEST")
        if not self.read_only:
            raise ValueError("binding_must_be_read_only")
        return self


class ModelVisibleToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_type: str = "TOOL_OBSERVATION"
    tool_call_id: str
    tool: str = Field(min_length=1)
    status: str
    data: dict[str, Any] | None = None
    error_summary: str | None = None
    source_identifier: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    artifact_sha256: str

    @field_validator("tool_call_id")
    @classmethod
    def _tc_namespace(cls, value: str) -> str:
        if not TOOL_CALL_ID_RE.fullmatch(value):
            raise ValueError("observation_requires_tc_id")
        return value


class ToolRuntimeLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tool_calls_per_repeat: int = Field(default=2, ge=1)
    max_calls_per_tool: int = Field(default=1, ge=1)
    max_tool_request_rounds: int = Field(default=2, ge=1)
    timeout_per_call_ms: int = Field(default=10_000, ge=1)
    total_tool_execution_budget_ms: int = Field(default=20_000, ge=1)
    automatic_retry: bool = False
    max_adapter_response_bytes: int = Field(default=131_072, ge=1024)
    max_model_visible_observation_bytes: int = Field(default=32_768, ge=1024)
    safe_http_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD"])

    @field_validator("automatic_retry")
    @classmethod
    def _no_retry(cls, value: bool) -> bool:
        if value:
            raise ValueError("automatic_retry_must_be_false_for_first_tool_live")
        return value


class ToolRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    limits: ToolRuntimeLimits = Field(default_factory=ToolRuntimeLimits)


class ToolRuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1)
    repeat_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    case_binding_id: str = Field(min_length=1)
    formal_allowed_tools: list[str] = Field(default_factory=list)
    prohibited_tools: list[str] = Field(default_factory=list)
    experiment_allowed_tools: list[str] = Field(default_factory=list)
    candidate_allowed_tools: list[str] = Field(default_factory=list)


class AdapterExecution(BaseModel):
    """Adapter return type. No HTTP assumptions are required by the C1 core."""

    model_config = ConfigDict(extra="forbid")
    status: ToolRuntimeStatus
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    latency_ms: int = Field(ge=0)
    response_artifact: Any | None = None
    source_system: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    observed_at: str = Field(default_factory=utc_now)
    auth_scope: str = "READ_ONLY"
    sensitive_fields_removed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_consistency(self) -> "AdapterExecution":
        if self.auth_scope != "READ_ONLY":
            raise ValueError("adapter_auth_scope_must_be_READ_ONLY")
        if self.status == ToolRuntimeStatus.SUCCESS and self.error is not None:
            raise ValueError("adapter_success_must_not_have_error")
        if self.status != ToolRuntimeStatus.SUCCESS and self.error is None:
            raise ValueError("adapter_failure_requires_error")
        return self


class ToolAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def invoke(
        self,
        request: ToolInvocationRequest,
        binding: CaseResourceBinding,
        *,
        timeout_ms: int,
        max_response_bytes: int,
    ) -> AdapterExecution: ...


class ResourceBindingResolver(Protocol):
    def resolve(self, case_binding_id: str, case_id: str) -> CaseResourceBinding: ...


class AuditArtifactSink(Protocol):
    def put(self, kind: str, payload: Any) -> str: ...


class InMemoryArtifactSink:
    def __init__(self) -> None:
        self.artifacts: dict[str, dict[str, Any]] = {}

    def put(self, kind: str, payload: Any) -> str:
        sanitized, removed = sanitize_for_audit(payload)
        wrapper = {"kind": kind, "payload": sanitized, "sanitized_fields": removed}
        digest = sha256_artifact(wrapper)
        self.artifacts[digest] = wrapper
        return digest


class InMemoryBindingResolver:
    def __init__(self, bindings: Sequence[CaseResourceBinding]) -> None:
        self._bindings = {x.case_binding_id: x for x in bindings}

    def resolve(self, case_binding_id: str, case_id: str) -> CaseResourceBinding:
        binding = self._bindings.get(case_binding_id)
        if binding is None or binding.case_id != case_id:
            raise KeyError("binding_not_found_or_case_mismatch")
        return binding


class ToolRegistry:
    def __init__(self, specs: Sequence[ToolSpec] | None = None) -> None:
        self._by_formal: dict[str, ToolSpec] = {}
        self._by_executable: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.executable_tool_id in self._by_executable:
            raise ValueError(f"duplicate_executable_tool_id:{spec.executable_tool_id}")
        for name in spec.formal_capabilities:
            if name in self._by_formal:
                raise ValueError(f"duplicate_formal_tool_name:{name}")
        self._by_executable[spec.executable_tool_id] = spec
        for name in spec.formal_capabilities:
            self._by_formal[name] = spec

    def resolve_formal(self, formal_tool_name: str) -> ToolSpec | None:
        return self._by_formal.get(formal_tool_name)

    def resolve_executable(self, executable_tool_id: str) -> ToolSpec | None:
        return self._by_executable.get(executable_tool_id)

    def formal_to_executable(self, formal_tool_name: str) -> str | None:
        spec = self.resolve_formal(formal_tool_name)
        return spec.executable_tool_id if spec else None

    def specs(self) -> list[ToolSpec]:
        return list(self._by_executable.values())


@dataclass
class ToolRuntimeSessionState:
    next_sequence: int = 1
    seen_message_refs: set[str] = field(default_factory=set)
    tool_request_rounds: int = 0
    accepted_call_count: int = 0
    per_tool_call_count: dict[str, int] = field(default_factory=dict)
    spent_execution_ms: int = 0
    issued_tool_call_ids: set[str] = field(default_factory=set)
    issued_audit_event_ids: set[str] = field(default_factory=set)


class RuntimeIdAuthority:
    def new_tool_call_id(self, state: ToolRuntimeSessionState) -> str:
        while True:
            candidate = "tc_" + uuid4().hex
            if candidate not in state.issued_tool_call_ids:
                state.issued_tool_call_ids.add(candidate)
                return candidate

    def new_audit_event_id(self, state: ToolRuntimeSessionState) -> str:
        while True:
            candidate = "ta_" + uuid4().hex
            if candidate not in state.issued_audit_event_ids:
                state.issued_audit_event_ids.add(candidate)
                return candidate


class FakeToolAdapter:
    """OFFLINE TEST ONLY adapter. Never performs network I/O."""

    def __init__(
        self,
        *,
        adapter_id: str = "fake-readonly-adapter",
        adapter_version: str = "test-only-v1",
        outcomes: Sequence[AdapterExecution] | None = None,
        outcome_factory: Callable[[ToolInvocationRequest, CaseResourceBinding], AdapterExecution] | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self._outcomes = list(outcomes or [])
        self._factory = outcome_factory
        self.calls: list[ToolInvocationRequest] = []

    def invoke(
        self,
        request: ToolInvocationRequest,
        binding: CaseResourceBinding,
        *,
        timeout_ms: int,
        max_response_bytes: int,
    ) -> AdapterExecution:
        self.calls.append(request)
        if self._factory is not None:
            return self._factory(request, binding)
        if self._outcomes:
            return self._outcomes.pop(0)
        return AdapterExecution(
            status=ToolRuntimeStatus.SUCCESS,
            data={"test_only": True, "echo": request.arguments},
            error=None,
            latency_ms=min(5, timeout_ms),
            response_artifact={"test_only": True, "echo": request.arguments},
            source_system="TEST_ONLY",
            source_identifier=f"test-only:{request.executable_tool_id}",
            auth_scope="READ_ONLY",
        )


@dataclass
class ToolRuntimeOutcome:
    invocation: ToolInvocationRequest | None = None
    blocked_event: BlockedInvocationAuditEvent | None = None
    result: ToolResultEnvelope | None = None
    tool_trace: dict[str, Any] | None = None
    model_observation: ModelVisibleToolObservation | None = None

    @property
    def blocked(self) -> bool:
        return self.blocked_event is not None


class ToolRuntimeCore:
    """C1 Tool execution core. It is deliberately not wired into app/client in this stage."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        adapters: Mapping[str, ToolAdapter],
        binding_resolver: ResourceBindingResolver,
        artifact_sink: AuditArtifactSink | None = None,
        config: ToolRuntimeConfig | None = None,
        id_authority: RuntimeIdAuthority | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = dict(adapters)
        self.binding_resolver = binding_resolver
        self.artifact_sink = artifact_sink or InMemoryArtifactSink()
        self.config = config or ToolRuntimeConfig()
        self.id_authority = id_authority or RuntimeIdAuthority()
        self.state = ToolRuntimeSessionState()

    def process_intent(self, payload: Mapping[str, Any], context: ToolRuntimeContext) -> ToolRuntimeOutcome:
        if not self.config.enabled:
            raise RuntimeError("tool_runtime_disabled")

        try:
            intent = ModelToolIntent.model_validate(payload)
        except Exception as exc:
            return ToolRuntimeOutcome(
                blocked_event=self._blocked_from_raw_payload(
                    payload,
                    context,
                    reason=BlockedReason.INVALID_ARGUMENTS,
                    stage=BlockedStage.TOOL_REQUEST_PARSER,
                    detail=f"parser_rejected:{exc.__class__.__name__}",
                )
            )

        sequence_reason = self._consume_sequence(intent)
        if sequence_reason is not None:
            return ToolRuntimeOutcome(
                blocked_event=self._blocked(intent, context, sequence_reason, BlockedStage.INVOCATION_GUARD)
            )

        spec = self.registry.resolve_formal(intent.requested_tool)
        if spec is None:
            return ToolRuntimeOutcome(
                blocked_event=self._blocked(intent, context, BlockedReason.UNKNOWN_TOOL, BlockedStage.INVOCATION_GUARD)
            )

        invocation = ToolInvocationRequest(
            run_id=context.run_id,
            repeat_id=context.repeat_id,
            case_id=context.case_id,
            candidate_id=context.candidate_id,
            requested_tool=intent.requested_tool,
            executable_tool_id=spec.executable_tool_id,
            arguments=dict(intent.arguments),
            request_sequence=intent.request_sequence,
            model_message_ref=intent.model_message_ref,
            case_binding_id=context.case_binding_id,
            created_at=utc_now(),
        )
        reason = self._guard(invocation, spec, context)
        if reason is not None:
            return ToolRuntimeOutcome(
                invocation=invocation,
                blocked_event=self._blocked(intent, context, reason, BlockedStage.INVOCATION_GUARD),
            )

        binding = self.binding_resolver.resolve(context.case_binding_id, context.case_id)
        tool_call_id = self.id_authority.new_tool_call_id(self.state)
        self.state.accepted_call_count += 1
        self.state.per_tool_call_count[spec.executable_tool_id] = self.state.per_tool_call_count.get(spec.executable_tool_id, 0) + 1
        result = self._dispatch(tool_call_id, invocation, spec, binding)
        self.state.spent_execution_ms += result.latency_ms
        trace = tool_result_to_workflow_trace(result, invocation)
        observation = make_model_visible_observation(result, self.config.limits.max_model_visible_observation_bytes)
        return ToolRuntimeOutcome(invocation=invocation, result=result, tool_trace=trace, model_observation=observation)

    def _consume_sequence(self, intent: ModelToolIntent) -> BlockedReason | None:
        if intent.model_message_ref in self.state.seen_message_refs:
            return BlockedReason.REPLAY_DETECTED
        if intent.request_sequence != self.state.next_sequence:
            return BlockedReason.REQUEST_SEQUENCE_INVALID
        if self.state.tool_request_rounds >= self.config.limits.max_tool_request_rounds:
            return BlockedReason.BUDGET_EXHAUSTED
        self.state.seen_message_refs.add(intent.model_message_ref)
        self.state.tool_request_rounds += 1
        self.state.next_sequence += 1
        return None

    def _guard(
        self,
        request: ToolInvocationRequest,
        spec: ToolSpec,
        context: ToolRuntimeContext,
    ) -> BlockedReason | None:
        allowed = set(context.formal_allowed_tools)
        if request.requested_tool not in allowed:
            return BlockedReason.CASE_NOT_ALLOWED
        if request.requested_tool in set(context.prohibited_tools):
            return BlockedReason.PROHIBITED_TOOL
        if context.experiment_allowed_tools and request.requested_tool not in set(context.experiment_allowed_tools):
            return BlockedReason.EXPERIMENT_NOT_ALLOWED
        if context.candidate_allowed_tools and request.requested_tool not in set(context.candidate_allowed_tools):
            return BlockedReason.CANDIDATE_NOT_ALLOWED
        if not spec.enabled:
            return BlockedReason.REGISTRY_DISABLED
        if context.case_id not in set(spec.allowed_cases):
            return BlockedReason.CASE_NOT_ALLOWED
        if spec.side_effect_class != SideEffectClass.READ_ONLY:
            return BlockedReason.NON_READ_ONLY_OPERATION
        safe_methods = set(x.upper() for x in self.config.limits.safe_http_methods)
        if any(method.upper() not in safe_methods for method in spec.allowed_methods):
            return BlockedReason.NON_READ_ONLY_OPERATION

        findings = _walk_values(request.arguments)
        if findings:
            first = findings[0][0]
            return BlockedReason(first)

        validator = Draft202012Validator(spec.argument_schema)
        if list(validator.iter_errors(request.arguments)):
            return BlockedReason.INVALID_ARGUMENTS

        try:
            binding = self.binding_resolver.resolve(request.case_binding_id, request.case_id)
        except Exception:
            return BlockedReason.WRONG_CASE_BINDING
        if not binding.read_only:
            return BlockedReason.NON_READ_ONLY_OPERATION
        if request.executable_tool_id not in set(binding.allowed_executable_tools):
            return BlockedReason.WRONG_CASE_BINDING

        limits = self.config.limits
        if self.state.accepted_call_count >= limits.max_tool_calls_per_repeat:
            return BlockedReason.BUDGET_EXHAUSTED
        if self.state.per_tool_call_count.get(spec.executable_tool_id, 0) >= limits.max_calls_per_tool:
            return BlockedReason.BUDGET_EXHAUSTED
        if self.state.spent_execution_ms >= limits.total_tool_execution_budget_ms:
            return BlockedReason.BUDGET_EXHAUSTED
        return None

    def _dispatch(
        self,
        tool_call_id: str,
        request: ToolInvocationRequest,
        spec: ToolSpec,
        binding: CaseResourceBinding,
    ) -> ToolResultEnvelope:
        limits = self.config.limits
        remaining_ms = max(1, limits.total_tool_execution_budget_ms - self.state.spent_execution_ms)
        effective_timeout_ms = min(limits.timeout_per_call_ms, remaining_ms)
        sanitized_request, removed = sanitize_for_audit(request.model_dump())
        request_hash = self.artifact_sink.put("tool_invocation_request", sanitized_request)
        adapter = self.adapters.get(spec.adapter_id)
        started = time.monotonic()

        # Registry identity is the expected binding. Runtime adapter identity is the
        # observed executor identity and must match before any adapter invocation.
        observed_adapter_id = str(getattr(adapter, "adapter_id", "UNBOUND")) if adapter is not None else "UNBOUND"
        observed_adapter_version = str(getattr(adapter, "adapter_version", "UNBOUND")) if adapter is not None else "UNBOUND"
        identity_matches = (
            adapter is not None
            and observed_adapter_id == spec.adapter_id
            and observed_adapter_version == spec.adapter_version
        )

        if adapter is None:
            adapter_execution = AdapterExecution(
                status=ToolRuntimeStatus.TOOL_ERROR,
                data=None,
                error=ToolError(code="ADAPTER_NOT_BOUND", message="Registry adapter is not bound in runtime.", retriable=False),
                latency_ms=0,
                response_artifact=None,
                source_system="RUNTIME",
                source_identifier=spec.executable_tool_id,
                auth_scope="READ_ONLY",
            )
        elif not identity_matches:
            # Guard has accepted the logical invocation and tc_ exists, but the
            # runtime executor identity fails closed before any external call.
            adapter_execution = AdapterExecution(
                status=ToolRuntimeStatus.SAFETY_BLOCKED,
                data=None,
                error=ToolError(
                    code="ADAPTER_IDENTITY_MISMATCH",
                    message="Runtime adapter identity does not match the registry binding.",
                    retriable=False,
                ),
                latency_ms=0,
                response_artifact=None,
                source_system="RUNTIME",
                source_identifier=f"adapter-identity-guard:{spec.executable_tool_id}",
                auth_scope="READ_ONLY",
            )
        else:
            try:
                adapter_execution = adapter.invoke(
                    request,
                    binding,
                    timeout_ms=effective_timeout_ms,
                    max_response_bytes=limits.max_adapter_response_bytes,
                )
            except TimeoutError:
                adapter_execution = AdapterExecution(
                    status=ToolRuntimeStatus.TIMEOUT,
                    data=None,
                    error=ToolError(code="TIMEOUT", message="Tool adapter timed out.", retriable=False),
                    latency_ms=effective_timeout_ms,
                    response_artifact=None,
                    source_system="RUNTIME",
                    source_identifier=spec.executable_tool_id,
                    auth_scope="READ_ONLY",
                )
            except Exception as exc:
                adapter_execution = AdapterExecution(
                    status=ToolRuntimeStatus.TOOL_ERROR,
                    data=None,
                    error=ToolError(code="ADAPTER_EXCEPTION", message=exc.__class__.__name__, retriable=False),
                    latency_ms=max(0, int((time.monotonic() - started) * 1000)),
                    response_artifact=None,
                    source_system="RUNTIME",
                    source_identifier=spec.executable_tool_id,
                    auth_scope="READ_ONLY",
                )

        status = adapter_execution.status
        latency_ms = max(adapter_execution.latency_ms, int((time.monotonic() - started) * 1000))
        if latency_ms > effective_timeout_ms and status == ToolRuntimeStatus.SUCCESS:
            # C1-r1 can normalize a call that returns after the budget, but it
            # cannot forcibly interrupt a blocking adapter. Hard network timeout
            # remains a real-adapter responsibility.
            status = ToolRuntimeStatus.TIMEOUT
            adapter_execution = adapter_execution.model_copy(
                update={
                    "status": status,
                    "data": None,
                    "error": ToolError(code="TIMEOUT", message="Tool call exceeded runtime timeout.", retriable=False),
                    "response_artifact": None,
                }
            )
            latency_ms = effective_timeout_ms

        response_hash: str | None = None
        safe_data: dict[str, Any] | None = None

        # Size-check the adapter material before any model-visible projection.
        response_material = adapter_execution.response_artifact
        if response_material is not None:
            try:
                raw_response_size = len(canonical_json_bytes(response_material))
            except Exception:
                raw_response_size = limits.max_adapter_response_bytes + 1
            if raw_response_size > limits.max_adapter_response_bytes:
                status = ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR
                adapter_execution = adapter_execution.model_copy(
                    update={
                        "status": status,
                        "data": None,
                        "error": ToolError(code="RESPONSE_TOO_LARGE", message="Adapter response exceeded runtime limit.", retriable=False),
                        "response_artifact": None,
                    }
                )
            else:
                sanitized_response, response_removed = sanitize_for_audit(response_material)
                removed = sorted(set(removed + response_removed + adapter_execution.sensitive_fields_removed))
                response_hash = self.artifact_sink.put("tool_invocation_response", sanitized_response)
        else:
            removed = sorted(set(removed + adapter_execution.sensitive_fields_removed))

        if status == ToolRuntimeStatus.SUCCESS and adapter_execution.data is None:
            status = ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR
            adapter_execution = adapter_execution.model_copy(
                update={
                    "status": status,
                    "error": ToolError(code="SUCCESS_DATA_MISSING", message="SUCCESS result requires data.", retriable=False),
                }
            )

        if status == ToolRuntimeStatus.SUCCESS and adapter_execution.data is not None:
            safe_data, data_removed = sanitize_for_audit(adapter_execution.data)
            removed = sorted(set(removed + data_removed))

        safe_error = adapter_execution.error
        if safe_error is not None:
            sanitized_error, error_removed = sanitize_for_audit(safe_error.model_dump())
            removed = sorted(set(removed + [f"error.{x}" for x in error_removed]))
            safe_error = ToolError.model_validate(sanitized_error)

        # Successful provenance is authoritative only after actual adapter identity
        # was verified. For non-executed/mismatched paths, record observed runtime
        # identity rather than falsely claiming the registry identity executed.
        provenance_adapter_id = observed_adapter_id if adapter is not None else "UNBOUND"
        provenance_adapter_version = observed_adapter_version if adapter is not None else "UNBOUND"
        provenance = ToolProvenance(
            adapter_id=provenance_adapter_id,
            adapter_version=provenance_adapter_version,
            source_system=adapter_execution.source_system,
            source_identifier=adapter_execution.source_identifier,
            observed_at=adapter_execution.observed_at,
            auth_scope="READ_ONLY",
            request_artifact_sha256=request_hash,
            response_artifact_sha256=response_hash,
        )
        error = safe_error
        if status != ToolRuntimeStatus.SUCCESS and error is None:
            error = ToolError(code=status.value, message="Runtime normalized tool failure.", retriable=False)
        if status == ToolRuntimeStatus.SUCCESS:
            error = None

        audit_payload = {
            "tool_call_id": tool_call_id,
            "tool": request.requested_tool,
            "executable_tool_id": request.executable_tool_id,
            "status": status.value,
            "latency_ms": latency_ms,
            "provenance": provenance.model_dump(),
            "sanitization": {"credentials_removed": True, "sensitive_fields_removed": removed},
        }
        audit_hash = self.artifact_sink.put("tool_result_audit", audit_payload)
        return ToolResultEnvelope(
            tool_call_id=tool_call_id,
            tool=request.requested_tool,
            executable_tool_id=request.executable_tool_id,
            status=status,
            data=safe_data if status == ToolRuntimeStatus.SUCCESS else None,
            error=error,
            latency_ms=latency_ms,
            attempt=1,
            provenance=provenance,
            sanitization=SanitizationState(credentials_removed=True, sensitive_fields_removed=removed),
            audit_artifact_sha256=audit_hash,
        )

    def _blocked(
        self,
        intent: ModelToolIntent,
        context: ToolRuntimeContext,
        reason: BlockedReason,
        stage: BlockedStage,
    ) -> BlockedInvocationAuditEvent:
        sanitized_args, removed = sanitize_for_audit(intent.arguments)
        audit_id = self.id_authority.new_audit_event_id(self.state)
        base = {
            "audit_event_id": audit_id,
            "run_id": context.run_id,
            "repeat_id": context.repeat_id,
            "case_id": context.case_id,
            "candidate_id": context.candidate_id,
            "requested_tool": intent.requested_tool,
            "sanitized_arguments": sanitized_args,
            "request_sequence": intent.request_sequence,
            "model_message_ref": intent.model_message_ref,
            "blocked_reason": reason.value,
            "blocked_stage": stage.value,
            "created_at": utc_now(),
            "external_call_started": False,
            "evidence_eligible": False,
            "sanitization": {"credentials_removed": True, "sensitive_fields_removed": removed},
        }
        artifact_hash = self.artifact_sink.put("blocked_invocation", base)
        return BlockedInvocationAuditEvent(**base, artifact_sha256=artifact_hash)

    def _blocked_from_raw_payload(
        self,
        payload: Mapping[str, Any],
        context: ToolRuntimeContext,
        *,
        reason: BlockedReason,
        stage: BlockedStage,
        detail: str,
    ) -> BlockedInvocationAuditEvent:
        raw_args = payload.get("arguments") if isinstance(payload.get("arguments"), Mapping) else {}
        sanitized_args, removed = sanitize_for_audit(raw_args)
        requested_tool = str(payload.get("requested_tool") or "<invalid-tool-intent>")[:128]
        seq = payload.get("request_sequence")
        seq_int = seq if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1 else 1
        msg_ref = str(payload.get("model_message_ref") or "parser-invalid")[:256]
        audit_id = self.id_authority.new_audit_event_id(self.state)
        base = {
            "audit_event_id": audit_id,
            "run_id": context.run_id,
            "repeat_id": context.repeat_id,
            "case_id": context.case_id,
            "candidate_id": context.candidate_id,
            "requested_tool": requested_tool,
            "sanitized_arguments": sanitized_args,
            "request_sequence": seq_int,
            "model_message_ref": msg_ref or "parser-invalid",
            "blocked_reason": reason.value,
            "blocked_stage": stage.value,
            "created_at": utc_now(),
            "external_call_started": False,
            "evidence_eligible": False,
            "sanitization": {"credentials_removed": True, "sensitive_fields_removed": removed},
            "parser_detail": detail,
        }
        artifact_payload = dict(base)
        artifact_payload.pop("parser_detail")
        artifact_hash = self.artifact_sink.put("blocked_invocation", artifact_payload)
        return BlockedInvocationAuditEvent(**artifact_payload, artifact_sha256=artifact_hash)


def runtime_status_to_workflow_status(status: ToolRuntimeStatus) -> str:
    if status == ToolRuntimeStatus.SUCCESS:
        return "SUCCESS"
    if status == ToolRuntimeStatus.SAFETY_BLOCKED:
        return "BLOCKED"
    return "ERROR"


def tool_result_to_workflow_trace(result: ToolResultEnvelope, request: ToolInvocationRequest) -> dict[str, Any]:
    latency_source = result.provenance.source_system
    return {
        "tool_call_id": result.tool_call_id,
        "tool": result.tool,
        "status": runtime_status_to_workflow_status(result.status),
        "arguments": dict(request.arguments),
        "result": {
            "data": result.data,
            "provenance": result.provenance.model_dump(),
            "request_artifact_sha256": result.provenance.request_artifact_sha256,
            "response_artifact_sha256": result.provenance.response_artifact_sha256,
            "audit_artifact_sha256": result.audit_artifact_sha256,
            "runtime_status": result.status.value,
        },
        "error": result.error.model_dump() if result.error else None,
        "latency_ms": {
            "value": result.latency_ms,
            "availability": "AVAILABLE",
            "source": latency_source,
            "note": None,
        },
        "retry_count": 0,
        "evidence_refs": [],
        "unauthorized_attempt": False,
        "source": "GATEWAY_TOOL_ORCHESTRATOR",
    }


def blocked_event_to_workflow_projection(event: BlockedInvocationAuditEvent) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "tool_trace": [],
        "errors": [
            {
                "code": "TOOL_INVOCATION_GUARD_BLOCKED",
                "message": f"{event.blocked_reason.value}; audit_ref={event.audit_event_id}",
                "source": "RUNTIME",
                "retriable": False,
            }
        ],
        "output_patch": {"guardrail_triggered": True, "guardrail_blocked": True},
    }


def successful_tool_trace_index(tool_trace: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("tool_call_id")): row
        for row in tool_trace
        if row.get("status") == "SUCCESS" and TOOL_CALL_ID_RE.fullmatch(str(row.get("tool_call_id") or ""))
    }


def assert_evidence_source_ref_is_real_success(source_ref: str, tool_trace: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if AUDIT_EVENT_ID_RE.fullmatch(source_ref):
        raise ValueError(f"evidence_source_ref_is_blocked_audit_event:{source_ref}")
    if not TOOL_CALL_ID_RE.fullmatch(source_ref):
        raise ValueError(f"evidence_source_ref_invalid_tool_call_id:{source_ref}")
    row = successful_tool_trace_index(tool_trace).get(source_ref)
    if row is None:
        raise ValueError(f"evidence_source_ref_not_successful_tool_result:{source_ref}")
    return row


def link_evidence_ref(tool_trace: list[dict[str, Any]], *, evidence_id: str, source_ref: str) -> None:
    row = assert_evidence_source_ref_is_real_success(source_ref, tool_trace)
    refs = row.setdefault("evidence_refs", [])
    if evidence_id not in refs:
        refs.append(evidence_id)


def make_model_visible_observation(result: ToolResultEnvelope, max_bytes: int) -> ModelVisibleToolObservation:
    status = "SUCCESS" if result.status == ToolRuntimeStatus.SUCCESS else ("BLOCKED" if result.status == ToolRuntimeStatus.SAFETY_BLOCKED else "ERROR")
    data, _ = sanitize_for_model_observation(result.data)
    safe_error_summary, _ = sanitize_for_model_observation(result.error.message if result.error else None)
    base = {
        "observation_type": "TOOL_OBSERVATION",
        "tool_call_id": result.tool_call_id,
        "tool": result.tool,
        "status": status,
        "data": data,
        "error_summary": safe_error_summary,
        "source_identifier": result.provenance.source_identifier,
        "observed_at": result.provenance.observed_at,
        "artifact_sha256": result.audit_artifact_sha256,
    }
    if len(canonical_json_bytes(base)) > max_bytes:
        data_hash = sha256_artifact(data) if data is not None else None
        base["data"] = {"_observation_truncated": True, "full_data_sha256": data_hash}
        base["error_summary"] = (base["error_summary"] or "")[:1024] or None
    if len(canonical_json_bytes(base)) > max_bytes:
        raise ValueError("model_visible_observation_exceeds_limit")
    return ModelVisibleToolObservation.model_validate(base)


def build_test_r3_unbound_registry() -> ToolRegistry:
    """Production-intent mappings only. Disabled until C2/real adapter binding is approved."""

    query_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 4096}},
    }
    return ToolRegistry(
        [
            ToolSpec(
                formal_tool_name="知识库测试结果",
                formal_capabilities=["知识库测试结果"],
                executable_tool_id="dify_kb_retrieval_probe",
                adapter_id="DifyReadOnlyAdapter",
                adapter_version="UNBOUND_C1",
                side_effect_class=SideEffectClass.READ_ONLY,
                argument_schema=query_schema,
                allowed_methods=["GET"],
                allowed_cases=["TEST-R3"],
                enabled=False,
            ),
            ToolSpec(
                formal_tool_name="对话流节点配置读取",
                formal_capabilities=["对话流节点配置读取", "工作流版本/输入读取", "工具调用轨迹。"],
                executable_tool_id="dify_chatflow_retrieval_probe",
                adapter_id="DifyReadOnlyAdapter",
                adapter_version="UNBOUND_C1",
                side_effect_class=SideEffectClass.READ_ONLY,
                argument_schema=query_schema,
                allowed_methods=["GET"],
                allowed_cases=["TEST-R3"],
                enabled=False,
            ),
        ]
    )
