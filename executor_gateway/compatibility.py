from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field


class ExecuteRequest(BaseModel):
    """冻结 YuanqiLiveExecutor 发往未来Gateway的固定内部请求契约。"""

    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1)
    task: dict[str, Any]
    candidate: dict[str, Any]
    experiment_spec: dict[str, Any]


@dataclass(frozen=True)
class CompatibilityConfig:
    """纯转换配置。不得从环境变量或真实Secret自动读取。"""

    assistant_id: str
    user_id: str = "ai-poc-live-executor"
    environment: str = "UNKNOWN"
    tool_name_map: Mapping[str, str] | None = None
    custom_variables: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.assistant_id.strip():
            raise ValueError("assistant_id_required")
        if not self.user_id.strip():
            raise ValueError("user_id_required")
        env = self.environment.upper()
        if env not in {"UNKNOWN", "LOCAL", "STAGING", "PRODUCTION"}:
            raise ValueError("invalid_environment")
        object.__setattr__(self, "environment", env)
        tool_map = dict(self.tool_name_map or {})
        if not all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in tool_map.items()):
            raise ValueError("invalid_tool_name_map")
        object.__setattr__(self, "tool_name_map", tool_map)
        if self.custom_variables is not None:
            custom = dict(self.custom_variables)
            if not all(isinstance(k, str) and k and isinstance(v, str) for k, v in custom.items()):
                raise ValueError("custom_variables_must_be_string_map")
            object.__setattr__(self, "custom_variables", custom)



@dataclass(frozen=True)
class PlatformModelTurnEnvelope:
    """Validated Yuanqi model-turn envelope before branch-specific content parsing.

    This object contains platform metadata only. It does not grant authority to
    native platform tool traces and does not validate TOOL_REQUEST or FINAL.
    """

    choice: Mapping[str, Any]
    message: Mapping[str, Any]
    finish_reason: str
    native_tool_trace_present: bool


def load_agent_contract_validator() -> Draft202012Validator:
    path = Path(__file__).with_name("EXECUTOR_AGENT_OUTPUT_CONTRACT.schema.json")
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _execution_envelope(req: ExecuteRequest) -> dict[str, Any]:
    return {
        "run_id": req.run_id,
        "task": req.task,
        "candidate": req.candidate,
        "experiment_spec": req.experiment_spec,
    }


def build_yuanqi_api_request(
    request: ExecuteRequest | Mapping[str, Any],
    config: CompatibilityConfig,
) -> dict[str, Any]:
    """只构造 Yuanqi API-format JSON；绝不发送网络请求。"""

    req = request if isinstance(request, ExecuteRequest) else ExecuteRequest.model_validate(request)
    text = json.dumps(_execution_envelope(req), ensure_ascii=False, separators=(",", ":"))
    out: dict[str, Any] = {
        "assistant_id": config.assistant_id,
        "user_id": config.user_id,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
    if config.custom_variables is not None:
        out["custom_variables"] = dict(config.custom_variables)
    return out


def _json_if_possible(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _sum_numbers(values: list[int | float]) -> int | float | None:
    return sum(values) if values else None


def _extract_tool_trace(
    message: Mapping[str, Any],
    finish_reason: str,
    tool_name_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    steps = message.get("steps")
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise ValueError("yuanqi_message_steps_must_be_list")

    calls: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    tool_name_map = tool_name_map or {}
    for step in steps:
        if not isinstance(step, Mapping):
            raise ValueError("yuanqi_message_step_must_be_object")
        role = step.get("role")
        if role == "assistant":
            tool_calls = step.get("tool_calls")
            if tool_calls is None:
                tool_calls = []
            if not isinstance(tool_calls, list):
                raise ValueError("yuanqi_tool_calls_must_be_list")
            for raw in tool_calls:
                if not isinstance(raw, Mapping):
                    raise ValueError("yuanqi_tool_call_must_be_object")
                call_id = str(raw.get("id") or "").strip()
                fn = raw.get("function")
                if not isinstance(fn, Mapping):
                    raise ValueError("yuanqi_tool_call_function_must_be_object")
                fn_name = str(fn.get("name") or "").strip()
                if not call_id or not fn_name:
                    raise ValueError("yuanqi_tool_call_missing_id_or_name")
                args = _json_if_possible(fn.get("arguments") if "arguments" in fn else "{}")
                if not isinstance(args, Mapping):
                    args = {"_raw_arguments": fn.get("arguments")}
                row = {
                    "tool_call_id": call_id,
                    "tool": str(tool_name_map.get(fn_name, fn_name)),
                    "status": "SKIPPED",
                    "arguments": dict(args),
                    "result": None,
                    "error": None,
                    "latency_ms": None,
                    "retry_count": 0,
                    "evidence_refs": [],
                    "unauthorized_attempt": False,
                }
                calls.append(row)
                by_id[call_id] = row
        elif role == "tool":
            call_id = str(step.get("tool_call_id") or "").strip()
            if not call_id:
                raise ValueError("yuanqi_tool_step_missing_tool_call_id")
            row = by_id.get(call_id)
            if row is None:
                # 不猜工具名；让冻结执行一致性门禁识别 unknown_tool。
                row = {
                    "tool_call_id": call_id,
                    "tool": "unknown_tool",
                    "status": "SKIPPED",
                    "arguments": {},
                    "result": None,
                    "error": None,
                    "latency_ms": None,
                    "retry_count": 0,
                    "evidence_refs": [],
                    "unauthorized_attempt": False,
                }
                calls.append(row)
                by_id[call_id] = row
            row["result"] = _json_if_possible(step.get("content"))
            row["status"] = "SUCCESS"
            row["latency_ms"] = _number(step.get("time_cost"))

    if finish_reason == "tool_fail":
        for row in calls:
            if row["status"] != "SUCCESS":
                row["status"] = "ERROR"
                row["error"] = {
                    "code": "YUANQI_TOOL_FAIL",
                    "message": "Mock Yuanqi响应finish_reason=tool_fail。",
                }
    return calls


def _step_latency(message: Mapping[str, Any]) -> dict[str, int | float | None]:
    steps = message.get("steps")
    if not isinstance(steps, list):
        return {"total_ms": None, "model_ms": None, "tool_ms": None, "queue_ms": None}
    model: list[int | float] = []
    tool: list[int | float] = []
    total: list[int | float] = []
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        value = _number(step.get("time_cost"))
        if value is None:
            continue
        total.append(value)
        if step.get("role") == "assistant":
            model.append(value)
        elif step.get("role") == "tool":
            tool.append(value)
    return {
        "total_ms": _sum_numbers(total),
        "model_ms": _sum_numbers(model),
        "tool_ms": _sum_numbers(tool),
        "queue_ms": None,
    }


def _usage(payload: Mapping[str, Any]) -> dict[str, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}

    def token(name: str) -> int | None:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    return {
        "input_tokens": token("prompt_tokens"),
        "output_tokens": token("completion_tokens"),
        "total_tokens": token("total_tokens"),
        "cache_hit_tokens": None,
        "cache_miss_tokens": None,
    }


def _failure_semantics(finish_reason: str) -> dict[str, Any] | None:
    if finish_reason == "tool_fail":
        return {
            "status": "FAILED",
            "output": {
                "final_action": "HANDOFF",
                "diagnosis_code": "YUANQI_TOOL_FAIL",
                "response": "Yuanqi执行返回tool_fail，候选执行未成功完成。",
                "root_cause": "Yuanqi响应finish_reason=tool_fail。",
                "confidence": "HIGH",
                "handoff_type": "RUNTIME",
                "guardrail_blocked": False,
                "guardrail_triggered": False,
                "root_cause_evidence_refs": [],
                "checks": {"yuanqi_finish_reason": "tool_fail"},
            },
            "quality_metrics": {
                "candidate_reported_task_success": False,
                "candidate_reported_score": None,
                "metric_breakdown": {},
            },
            "evidence": [],
            "errors": [
                {
                    "code": "YUANQI_TOOL_FAIL",
                    "message": "Yuanqi工具调用失败。",
                    "source": "TOOL",
                    "retriable": False,
                }
            ],
        }
    if finish_reason == "sensitive":
        return {
            "status": "BLOCKED",
            "output": {
                "final_action": "REFUSE",
                "diagnosis_code": "YUANQI_SENSITIVE_BLOCK",
                "response": "Yuanqi执行被内容安全审核阻断。",
                "root_cause": "Yuanqi响应finish_reason=sensitive。",
                "confidence": "HIGH",
                "handoff_type": "POLICY",
                "guardrail_blocked": True,
                "guardrail_triggered": True,
                "root_cause_evidence_refs": [],
                "checks": {"yuanqi_finish_reason": "sensitive"},
            },
            "quality_metrics": {
                "candidate_reported_task_success": False,
                "candidate_reported_score": None,
                "metric_breakdown": {},
            },
            "evidence": [],
            "errors": [
                {
                    "code": "YUANQI_SENSITIVE_BLOCK",
                    "message": "Yuanqi内容安全审核不通过。",
                    "source": "POLICY",
                    "retriable": False,
                }
            ],
        }
    return None


_JSON_WS = " \t\r\n"


def _looks_like_json_text(text: str) -> bool:
    """Only classify obvious JSON-looking text; never search/extract embedded fragments."""

    if not text:
        return False
    first = text[0]
    if first in '{["-0123456789':
        return True
    return text.startswith(("true", "false", "null"))


def _unwrap_single_json_fence(text: str) -> str:
    """Remove exactly one complete outer ```json ... ``` fence and nothing else.

    Only the language tag ``json`` (case-insensitive) is accepted. Unlabelled or
    other-language fences are rejected. The inner payload is returned byte-for-
    byte at the Python string level except for removal of the two outer fence
    lines; no prose stripping, fragment extraction, or JSON repair is performed.
    """

    first_lf = text.find("\n")
    if first_lf < 0:
        raise ValueError("yuanqi_agent_content_outer_format_invalid")
    opening = text[:first_lf]
    if opening.endswith("\r"):
        opening = opening[:-1]
    if opening.lower() != "```json":
        raise ValueError("yuanqi_agent_content_outer_format_invalid")

    closing_marker = "\n```"
    closing_start = text.rfind(closing_marker)
    if closing_start < first_lf or closing_start + len(closing_marker) != len(text):
        raise ValueError("yuanqi_agent_content_outer_format_invalid")

    return text[first_lf + 1 : closing_start]


def _reject_nonstandard_json_constant(token: str) -> None:
    """Reject NaN/Infinity/-Infinity at parse time; never coerce them."""

    raise ValueError(f"yuanqi_agent_content_nonstandard_number:{token}")


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate keys at every nesting level."""

    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"yuanqi_agent_content_duplicate_key:{key}")
        out[key] = value
    return out


def _assert_finite_json_numbers(value: Any) -> None:
    """Reject float overflow results such as 1e999 -> inf, recursively."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("yuanqi_agent_content_nonfinite_number")
        return
    if isinstance(value, Mapping):
        for child in value.values():
            _assert_finite_json_numbers(child)
        return
    if isinstance(value, list):
        for child in value:
            _assert_finite_json_numbers(child)


def _strict_json_loads(text: str) -> Any:
    """Parse RFC-style JSON without Python's NaN/Infinity or duplicate-key leniency."""

    try:
        data = json.loads(
            text,
            parse_constant=_reject_nonstandard_json_constant,
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("yuanqi_agent_content_invalid_json") from exc
    _assert_finite_json_numbers(data)
    return data


def parse_executor_agent_json_strict(content: Any) -> dict[str, Any]:
    """Parse Executor model output using strict fail-closed transport normalization.

    Accepted forms:
    A) native JSON text whose root is an object;
    B) one complete outer ```json ... ``` fence (``json`` case-insensitive),
       with no non-whitespace content outside the fence.

    This function never repairs JSON or extracts a JSON-looking substring. It
    also rejects Python's non-standard JSON constants, non-finite numeric
    overflow, and duplicate object keys.
    """

    if not isinstance(content, str):
        raise ValueError("yuanqi_agent_content_outer_format_invalid")
    text = content.strip(_JSON_WS)
    if not text:
        raise ValueError("yuanqi_agent_content_missing")

    try:
        data = _strict_json_loads(text)
    except ValueError as native_exc:
        if text.startswith("```"):
            inner = _unwrap_single_json_fence(text)
            try:
                data = _strict_json_loads(inner)
            except ValueError as exc:
                raise exc
        elif _looks_like_json_text(text):
            raise native_exc
        else:
            raise ValueError("yuanqi_agent_content_outer_format_invalid") from native_exc

    if not isinstance(data, Mapping):
        raise ValueError("yuanqi_agent_content_root_must_be_object")
    return dict(data)


def _semantic_from_content(content: Any, validator: Draft202012Validator) -> dict[str, Any]:
    data = parse_executor_agent_json_strict(content)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(x) for x in first.absolute_path)
        raise ValueError(f"yuanqi_agent_content_contract_invalid:{path}:{first.message}")
    return data


def _materialize_evidence(
    semantic: Mapping[str, Any],
    tool_trace: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {row["tool_call_id"]: row for row in tool_trace if row.get("status") == "SUCCESS"}
    out: list[dict[str, Any]] = []
    for raw in semantic.get("evidence") or []:
        source_ref = str(raw["source_ref"])
        tool = by_id.get(source_ref)
        if tool is None:
            raise ValueError(f"evidence_source_ref_not_real_tool_result:{source_ref}")
        result = tool.get("result")
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, sort_keys=True)
        row = {
            "evidence_id": str(raw["evidence_id"]),
            "evidence_type": "TOOL_OBSERVATION",
            "claim": str(raw["claim"]),
            "source_ref": source_ref,
            "support_level": str(raw["support_level"]),
            "content": content,
            "claim_ids": [str(x) for x in raw.get("claim_ids") or []],
            "target": raw.get("target"),
            "action": tool.get("tool"),
            "result": content,
        }
        out.append(row)
        tool["evidence_refs"].append(row["evidence_id"])
    ids = {row["evidence_id"] for row in out}
    dangling = [x for x in semantic.get("root_cause_evidence_refs") or [] if x not in ids]
    if dangling:
        raise ValueError("root_cause_evidence_ref_missing:" + ",".join(map(str, dangling)))
    return out



def normalize_gateway_orchestrated_final(
    semantic: Mapping[str, Any],
    authoritative_tool_trace: Sequence[Mapping[str, Any]],
    validator: Draft202012Validator | None = None,
) -> dict[str, Any]:
    """Validate a C2 FINAL against the existing Final authority and Gateway trace.

    The supplied tool trace is the current Gateway Orchestrator session trace.
    Yuanqi native ``message.steps``/``tool_calls`` are deliberately not accepted
    as an input to this function. Evidence materialization therefore has exactly
    one authority in C2: current-session Gateway SUCCESS ``tc_`` records.
    """

    if not isinstance(semantic, Mapping):
        raise ValueError("gateway_final_root_must_be_object")
    validator = validator or load_agent_contract_validator()
    data = dict(semantic)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(x) for x in first.absolute_path)
        raise ValueError(f"gateway_final_contract_invalid:{path}:{first.message}")

    # Work on a deep copy so Evidence linking never mutates the Orchestrator's
    # authoritative session ledger as a side effect of validation.
    trace = deepcopy([dict(row) for row in authoritative_tool_trace])
    evidence = _materialize_evidence(data, trace)
    return {
        "status": data["status"],
        "output": {
            "final_action": data["final_action"],
            "diagnosis_code": data["diagnosis_code"],
            "response": data["response"],
            "root_cause": data["root_cause"],
            "confidence": data["confidence"],
            "handoff_type": data["handoff_type"],
            "guardrail_blocked": data["guardrail_blocked"],
            "guardrail_triggered": data["guardrail_triggered"],
            "root_cause_evidence_refs": list(data["root_cause_evidence_refs"]),
            "checks": dict(data["checks"]),
        },
        "quality_metrics": {
            "candidate_reported_task_success": data["candidate_reported_task_success"],
            "candidate_reported_score": data["candidate_reported_score"],
            "metric_breakdown": dict(data["metric_breakdown"]),
        },
        "evidence": evidence,
        "errors": [],
        "tool_trace": trace,
    }


def _native_tool_trace_present(message: Mapping[str, Any]) -> bool:
    direct = message.get("tool_calls")
    if direct is not None:
        if isinstance(direct, list):
            if direct:
                return True
        else:
            # Gateway orchestration must fail closed on malformed/unknown
            # native trace surfaces. Only the documented empty list is a
            # known-safe direct tool_calls value; a non-list shape must not
            # be silently treated as "no native trace".
            return True
    steps = message.get("steps")
    if steps is None:
        return False
    if not isinstance(steps, list):
        # Malformed native trace surface is unsafe in Gateway-orchestrated mode.
        return True
    for step in steps:
        if not isinstance(step, Mapping):
            return True
        if step.get("role") == "tool":
            return True
        calls = step.get("tool_calls")
        if isinstance(calls, list) and calls:
            return True
        if calls is not None and not isinstance(calls, list):
            return True
    return False


def validate_platform_model_turn_envelope(
    payload: Mapping[str, Any],
    *,
    allowed_finish_reasons: Sequence[str],
) -> PlatformModelTurnEnvelope:
    """Apply the shared Yuanqi platform-safety envelope gate for one model turn."""

    if not isinstance(payload, Mapping):
        raise ValueError("yuanqi_response_root_must_be_object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("yuanqi_choices_empty")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ValueError("yuanqi_choice_must_be_object")
    finish_reason = str(choice.get("finish_reason") or "").strip()
    if finish_reason not in set(allowed_finish_reasons):
        raise ValueError("yuanqi_finish_reason_unsupported")
    _validate_platform_completion_safety(choice)
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("yuanqi_message_must_be_object")
    return PlatformModelTurnEnvelope(
        choice=choice,
        message=message,
        finish_reason=finish_reason,
        native_tool_trace_present=_native_tool_trace_present(message),
    )

def _validate_platform_completion_safety(choice: Mapping[str, Any]) -> None:
    """Fail closed on Yuanqi moderation semantics before consuming model content.

    Missing/null/blank moderation_level keeps the existing path. Documented values
    "1" (end session) and "2" (withdraw response) are not consumable by this
    single-turn Executor contract, and unknown non-empty values are unsafe by
    default. No message.content is inspected or echoed here.
    """

    if "moderation_level" not in choice or choice.get("moderation_level") is None:
        return
    raw = choice.get("moderation_level")
    if not isinstance(raw, str):
        raise ValueError("yuanqi_moderation_level_invalid_type")
    level = raw.strip()
    if not level:
        return
    if level == "1":
        raise ValueError("yuanqi_moderation_level_session_end")
    if level == "2":
        raise ValueError("yuanqi_moderation_level_content_withdrawn")
    raise ValueError("yuanqi_moderation_level_unsupported")


def normalize_yuanqi_response(
    payload: Mapping[str, Any],
    config: CompatibilityConfig,
    validator: Draft202012Validator | None = None,
) -> dict[str, Any]:
    """把Yuanqi格式响应规范化成冻结 YuanqiResponseAdapter 可消费的稳定object；测试阶段仅使用fixture/MockTransport。"""

    validator = validator or load_agent_contract_validator()
    turn = validate_platform_model_turn_envelope(
        payload,
        allowed_finish_reasons=("stop", "tool_fail", "sensitive"),
    )
    finish_reason = turn.finish_reason
    message = turn.message

    tool_trace = _extract_tool_trace(message, finish_reason, config.tool_name_map)
    failure = _failure_semantics(finish_reason)
    if failure is None:
        semantic = _semantic_from_content(message.get("content"), validator)
        evidence = _materialize_evidence(semantic, tool_trace)
        execution = {
            "status": semantic["status"],
            "output": {
                "final_action": semantic["final_action"],
                "diagnosis_code": semantic["diagnosis_code"],
                "response": semantic["response"],
                "root_cause": semantic["root_cause"],
                "confidence": semantic["confidence"],
                "handoff_type": semantic["handoff_type"],
                "guardrail_blocked": semantic["guardrail_blocked"],
                "guardrail_triggered": semantic["guardrail_triggered"],
                "root_cause_evidence_refs": list(semantic["root_cause_evidence_refs"]),
                "checks": dict(semantic["checks"]),
            },
            "quality_metrics": {
                "candidate_reported_task_success": semantic["candidate_reported_task_success"],
                "candidate_reported_score": semantic["candidate_reported_score"],
                "metric_breakdown": dict(semantic["metric_breakdown"]),
            },
            "evidence": evidence,
            "errors": [],
        }
    else:
        execution = failure

    execution["tool_trace"] = tool_trace
    execution["latency"] = _step_latency(message)
    # Mock响应没有明确成本时必须保持空值，由冻结Adapter映射为NOT_PROVIDED。
    execution["cost"] = {"currency": None, "total": None, "model": None, "tool": None, "other": None}
    execution["token_usage"] = _usage(payload)

    remote_id = payload.get("id")
    if not isinstance(remote_id, str) or not remote_id.strip():
        raise ValueError("yuanqi_remote_execution_id_missing")
    raw_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "gateway_contract_version": "1.1-runtime-candidate",
        "execution": execution,
        "meta": {
            "remote_execution_id": remote_id,
            "assistant_id": payload.get("assistant_id"),
            "finish_reason": finish_reason,
            "created": payload.get("created"),
            "environment": config.environment,
            "upstream_response_sha256": "sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        },
    }
