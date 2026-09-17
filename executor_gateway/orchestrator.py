from __future__ import annotations

import hashlib
import json
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator

from .client import GatewayModerationBlocked, GatewayUpstreamError
from .config import (
    APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH,
    APPROVED_TOOL_ENABLED_PROMPT_SHA256,
    APPROVED_TOOL_ENABLED_PROMPT_VERSION,
)
from .compatibility import (
    ExecuteRequest,
    load_agent_contract_validator,
    normalize_gateway_orchestrated_final,
)
from .model_turn import ParseError, ParsedFinal, ParsedToolRequest, parse_model_turn
from .prompt_loader import LoadedPromptCandidate
from .tool_runtime import (
    ModelVisibleToolObservation,
    ToolRuntimeContext,
    ToolRuntimeCore,
    ToolRuntimeStatus,
    sanitize_for_model_observation,
)


class NextTurnMode(str, Enum):
    NORMAL = "NORMAL"
    FINAL_ONLY = "FINAL_ONLY"


class OrchestratorTerminalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


_C1C_PROMPT_GATE_SENTINEL = object()


@dataclass(frozen=True)
class OrchestratorConfig:
    """C2/C1C offline candidate gate. Production wiring remains absent."""

    enabled: bool = False
    tool_enabled_prompt_enabled: bool = False
    max_model_turns: int = 3
    max_tool_request_rounds: int = 2
    max_tool_calls_per_repeat: int = 2
    max_calls_per_executable_tool: int = 1
    _c1c_prompt_gate: InitVar[object | None] = None

    def __post_init__(self, _c1c_prompt_gate: object | None) -> None:
        frozen = (3, 2, 2, 1)
        actual = (
            self.max_model_turns,
            self.max_tool_request_rounds,
            self.max_tool_calls_per_repeat,
            self.max_calls_per_executable_tool,
        )
        if actual != frozen:
            raise ValueError("c2b_orchestrator_limits_must_match_frozen_contract")
        if self.tool_enabled_prompt_enabled and _c1c_prompt_gate is not _C1C_PROMPT_GATE_SENTINEL:
            # Preserve the frozen C2-BR1 direct-construction gate. C1C uses the
            # explicit factory below, while LoadedPromptCandidate validation
            # remains the actual fail-closed Prompt authority check.
            raise ValueError("tool_enabled_prompt_must_remain_disabled_in_c2b")

    @classmethod
    def for_c1c_tool_enabled_prompt(cls, *, enabled: bool = True) -> "OrchestratorConfig":
        return cls(
            enabled=enabled,
            tool_enabled_prompt_enabled=True,
            _c1c_prompt_gate=_C1C_PROMPT_GATE_SENTINEL,
        )


class ModelCallResultLike(Protocol):
    content: Any
    finish_reason: str
    remote_execution_id: str
    native_tool_trace_present: bool


class ModelCaller(Protocol):
    async def call_model_once(self, messages: list[Mapping[str, Any]]) -> ModelCallResultLike: ...


@dataclass(frozen=True)
class ToolInteraction:
    requested_tool: str
    arguments: dict[str, Any]
    observation: ModelVisibleToolObservation


@dataclass
class OrchestratorSession:
    current_model_turn: int = 0
    request_sequence: int = 1
    tool_request_rounds: int = 0
    next_turn_mode: NextTurnMode = NextTurnMode.NORMAL
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    blocked_audit_events: list[dict[str, Any]] = field(default_factory=list)
    interactions: list[ToolInteraction] = field(default_factory=list)


@dataclass(frozen=True)
class OrchestratorResult:
    terminal_status: OrchestratorTerminalStatus
    reason: str | None
    detail: str | None
    model_turns: int
    tool_request_rounds: int
    next_turn_mode: NextTurnMode
    tool_trace: list[dict[str, Any]]
    blocked_audit_events: list[dict[str, Any]]
    final_semantic: dict[str, Any] | None = None
    final_execution: dict[str, Any] | None = None


class GatewayMultiTurnOrchestrator:
    """Gateway-authoritative C2 multi-turn loop, offline candidate only.

    The model can emit only a Tool Intent or Final. Round authority, message
    references, Runtime call IDs, budgets, reinjection, and Evidence validation
    remain Gateway owned.
    """

    def __init__(
        self,
        *,
        model_caller: ModelCaller,
        tool_runtime: ToolRuntimeCore,
        config: OrchestratorConfig | None = None,
        final_validator: Draft202012Validator | None = None,
        loaded_prompt: LoadedPromptCandidate | None = None,
    ) -> None:
        self.model_caller = model_caller
        self.tool_runtime = tool_runtime
        self.config = config or OrchestratorConfig()
        self.final_validator = final_validator or load_agent_contract_validator()
        self.loaded_prompt = loaded_prompt
        self._validate_runtime_limits()
        self._validate_tool_enabled_prompt_gate()

    def _validate_tool_enabled_prompt_gate(self) -> None:
        if not self.config.tool_enabled_prompt_enabled:
            return
        prompt = self.loaded_prompt
        if prompt is None:
            raise ValueError("tool_enabled_prompt_candidate_required")
        if not isinstance(prompt, LoadedPromptCandidate):
            raise ValueError("tool_enabled_prompt_candidate_type_invalid")
        if prompt.version != APPROVED_TOOL_ENABLED_PROMPT_VERSION:
            raise ValueError("tool_enabled_prompt_candidate_version_mismatch")
        if prompt.logical_path != APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH:
            raise ValueError("tool_enabled_prompt_candidate_logical_path_mismatch")
        if prompt.sha256 != APPROVED_TOOL_ENABLED_PROMPT_SHA256:
            raise ValueError("tool_enabled_prompt_candidate_metadata_sha256_mismatch")
        if not prompt.text:
            raise ValueError("tool_enabled_prompt_candidate_empty")
        try:
            raw = prompt.text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("tool_enabled_prompt_candidate_invalid_utf8_text") from exc
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != prompt.sha256 or actual_sha256 != APPROVED_TOOL_ENABLED_PROMPT_SHA256:
            raise ValueError("tool_enabled_prompt_candidate_text_sha256_mismatch")

    def _validate_runtime_limits(self) -> None:
        limits = self.tool_runtime.config.limits
        expected = (
            self.config.max_tool_request_rounds,
            self.config.max_tool_calls_per_repeat,
            self.config.max_calls_per_executable_tool,
        )
        actual = (
            limits.max_tool_request_rounds,
            limits.max_tool_calls_per_repeat,
            limits.max_calls_per_tool,
        )
        if actual != expected:
            raise ValueError("c2b_runtime_limit_mismatch")
        if limits.automatic_retry:
            raise ValueError("c2b_runtime_retry_must_be_false")

    @staticmethod
    def _execution_context(request: ExecuteRequest) -> dict[str, Any]:
        raw = {
            "run_id": request.run_id,
            "task": request.task,
            "candidate": request.candidate,
            "experiment_spec": request.experiment_spec,
        }
        sanitized, _ = sanitize_for_model_observation(raw)
        if not isinstance(sanitized, dict):  # defensive type boundary
            raise ValueError("canonical_execution_context_invalid")
        return sanitized

    def build_canonical_messages(
        self,
        request: ExecuteRequest,
        session: OrchestratorSession,
        *,
        next_model_turn: int,
    ) -> list[dict[str, Any]]:
        """Strategy-B reconstruction: one deterministic user payload per turn."""

        interactions: list[dict[str, Any]] = []
        for item in session.interactions:
            safe_args, _ = sanitize_for_model_observation(item.arguments)
            interactions.append(
                {
                    "formal_tool_request": {
                        "requested_tool": item.requested_tool,
                        "arguments": safe_args,
                    },
                    "observation_trust": "UNTRUSTED_TOOL_DATA",
                    "observation": item.observation.model_dump(),
                }
            )

        context = {
            "gateway_protocol": "P1.4-C2-B-OFFLINE-CANDIDATE",
            "original_execution_context": self._execution_context(request),
            "gateway_session": {
                "current_model_turn": next_model_turn,
                "next_turn_mode": session.next_turn_mode.value,
                "max_model_turns": self.config.max_model_turns,
                "max_tool_request_rounds": self.config.max_tool_request_rounds,
                "tool_request_rounds_used": session.tool_request_rounds,
            },
            "tool_interactions": interactions,
            "trust_boundary": {
                "tool_observation_data": "UNTRUSTED_TOOL_DATA",
                "instruction_authority": "GATEWAY_AND_SYSTEM_POLICY_ONLY",
                "tool_call_id_authority": "GATEWAY_TOOL_RUNTIME_ONLY",
            },
        }
        text = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        user_message = {"role": "user", "content": [{"type": "text", "text": text}]}
        if not self.config.tool_enabled_prompt_enabled:
            return [user_message]

        prompt = self.loaded_prompt
        if prompt is None:  # constructor gate makes this unreachable; keep fail-closed.
            raise ValueError("tool_enabled_prompt_candidate_required")
        system_message = {
            "role": "system",
            "content": [{"type": "text", "text": prompt.text}],
        }
        return [system_message, user_message]

    def _result(
        self,
        session: OrchestratorSession,
        status: OrchestratorTerminalStatus,
        *,
        reason: str | None,
        detail: str | None = None,
        final_semantic: dict[str, Any] | None = None,
        final_execution: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        return OrchestratorResult(
            terminal_status=status,
            reason=reason,
            detail=detail,
            model_turns=session.current_model_turn,
            tool_request_rounds=session.tool_request_rounds,
            next_turn_mode=session.next_turn_mode,
            tool_trace=[dict(row) for row in session.tool_trace],
            blocked_audit_events=[dict(row) for row in session.blocked_audit_events],
            final_semantic=final_semantic,
            final_execution=final_execution,
        )

    async def run(
        self,
        request: ExecuteRequest | Mapping[str, Any],
        runtime_context: ToolRuntimeContext,
    ) -> OrchestratorResult:
        if not self.config.enabled:
            raise RuntimeError("c2b_multi_turn_orchestrator_disabled")
        if not self.tool_runtime.config.enabled:
            raise RuntimeError("c2b_tool_runtime_disabled")

        req = request if isinstance(request, ExecuteRequest) else ExecuteRequest.model_validate(request)
        session = OrchestratorSession()

        while session.current_model_turn < self.config.max_model_turns:
            next_turn = session.current_model_turn + 1
            messages = self.build_canonical_messages(req, session, next_model_turn=next_turn)
            try:
                model_result = await self.model_caller.call_model_once(messages)
            except GatewayModerationBlocked as exc:
                session.current_model_turn = next_turn
                return self._result(
                    session,
                    OrchestratorTerminalStatus.BLOCKED,
                    reason="MODEL_TURN_MODERATION_BLOCKED",
                    detail=str(exc),
                )
            except GatewayUpstreamError as exc:
                session.current_model_turn = next_turn
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="MODEL_CALL_FAILED_CLOSED",
                    detail=str(exc),
                )

            session.current_model_turn = next_turn

            if model_result.native_tool_trace_present:
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="UNEXPECTED_NATIVE_TOOL_TRACE_IN_GATEWAY_ORCHESTRATION",
                )

            finish_reason = model_result.finish_reason
            if finish_reason == "sensitive":
                return self._result(
                    session,
                    OrchestratorTerminalStatus.BLOCKED,
                    reason="MODEL_TURN_SENSITIVE",
                )
            if finish_reason == "length":
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="MODEL_OUTPUT_TRUNCATED",
                )
            if finish_reason == "tool_fail":
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="PLATFORM_MODEL_CALL_TOOL_FAIL",
                )
            if finish_reason != "stop":
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="UNSUPPORTED_FINISH_REASON",
                    detail=finish_reason,
                )

            parsed = parse_model_turn(model_result.content, final_validator=self.final_validator)
            if isinstance(parsed, ParseError):
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="MODEL_RESPONSE_PARSE_ERROR",
                    detail=f"{parsed.code}:{parsed.detail}",
                )

            if isinstance(parsed, ParsedFinal):
                try:
                    final_execution = normalize_gateway_orchestrated_final(
                        parsed.semantic,
                        session.tool_trace,
                        self.final_validator,
                    )
                except ValueError as exc:
                    return self._result(
                        session,
                        OrchestratorTerminalStatus.ERROR,
                        reason="FINAL_POST_VALIDATION_FAILED",
                        detail=str(exc),
                    )
                return self._result(
                    session,
                    OrchestratorTerminalStatus.SUCCESS,
                    reason=None,
                    final_semantic=parsed.semantic,
                    final_execution=final_execution,
                )

            if not isinstance(parsed, ParsedToolRequest):  # static exhaustiveness guard
                raise TypeError("unexpected_model_turn_variant")

            if session.next_turn_mode == NextTurnMode.FINAL_ONLY:
                return self._result(
                    session,
                    OrchestratorTerminalStatus.BLOCKED,
                    reason="TOOL_REQUEST_FORBIDDEN_AFTER_TOOL_FAILURE",
                )

            session.tool_request_rounds += 1
            model_message_ref = f"gateway-model-turn-{session.current_model_turn}"
            runtime_payload = {
                "turn_type": "TOOL_REQUEST",
                "requested_tool": parsed.request.requested_tool,
                "arguments": dict(parsed.request.arguments),
                "request_sequence": session.request_sequence,
                "model_message_ref": model_message_ref,
            }
            session.request_sequence += 1

            try:
                outcome = self.tool_runtime.process_intent(runtime_payload, runtime_context)
            except (ValueError, RuntimeError) as exc:
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="TOOL_OBSERVATION_UNSAFE_OR_INVALID",
                    detail=str(exc),
                )

            if outcome.blocked_event is not None:
                session.blocked_audit_events.append(outcome.blocked_event.model_dump(mode="json"))
                return self._result(
                    session,
                    OrchestratorTerminalStatus.BLOCKED,
                    reason=f"PRE_GUARD_BLOCKED:{outcome.blocked_event.blocked_reason.value}",
                )

            if outcome.result is None or outcome.tool_trace is None or outcome.model_observation is None:
                return self._result(
                    session,
                    OrchestratorTerminalStatus.ERROR,
                    reason="TOOL_RUNTIME_INCOMPLETE_OUTCOME",
                )

            session.tool_trace.append(dict(outcome.tool_trace))
            session.interactions.append(
                ToolInteraction(
                    requested_tool=parsed.request.requested_tool,
                    arguments=dict(parsed.request.arguments),
                    observation=outcome.model_observation,
                )
            )

            if outcome.result.status == ToolRuntimeStatus.SUCCESS:
                session.next_turn_mode = NextTurnMode.NORMAL
            else:
                # Every post-guard non-success result owns a legal tc_ and gets one
                # sanitized failure-observation reinjection, after which the model
                # is FINAL-only. This includes TIMEOUT, TOOL_ERROR/AUTH/HTTP/
                # validation errors, and SAFETY_BLOCKED.
                session.next_turn_mode = NextTurnMode.FINAL_ONLY

            if session.current_model_turn >= self.config.max_model_turns:
                return self._result(
                    session,
                    OrchestratorTerminalStatus.BLOCKED,
                    reason="MAX_MODEL_TURNS_EXCEEDED_BEFORE_FINAL",
                )

        return self._result(
            session,
            OrchestratorTerminalStatus.BLOCKED,
            reason="MAX_MODEL_TURNS_EXCEEDED_BEFORE_FINAL",
        )
