from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts"


class SchemaValidationError(ValueError):
    """契约校验或跨契约一致性校验失败。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_schema(name: str) -> dict[str, Any]:
    path = CONTRACTS_DIR / name
    if not path.exists():
        raise SchemaValidationError(f"schema_not_found:{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_payload(payload: Mapping[str, Any], schema_name: str) -> dict[str, Any]:
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda e: list(e.absolute_path))
    if errors:
        messages = []
        for error in errors:
            path = "$" + "".join(f"[{part!r}]" if isinstance(part, str) else f"[{part}]" for part in error.absolute_path)
            messages.append(f"{path}:{error.message}")
        raise SchemaValidationError(";".join(messages))
    return dict(payload)


def validate_task_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "task_input.schema.json")


def validate_candidate_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "candidate_plan.schema.json")


def validate_experiment_spec(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "experiment_spec.schema.json")


def validate_evaluation_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "evaluation_contract.schema.json")


def _is_available(metric: Mapping[str, Any]) -> bool:
    return metric.get("availability") in {"AVAILABLE", "ESTIMATED"} and metric.get("value") is not None


def _close(a: float, b: float, *, atol: float = 1e-6, rtol: float = 1e-6) -> bool:
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b), 1.0))


def _validate_metric_integrity(result: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []

    latency = result["latency"]
    latency_parts = [latency[k] for k in ("model_ms", "tool_ms", "queue_ms")]
    if _is_available(latency["total_ms"]) and all(_is_available(x) for x in latency_parts):
        expected = sum(float(x["value"]) for x in latency_parts)
        if not _close(float(latency["total_ms"]["value"]), expected, atol=1.0):
            issues.append("latency_total_component_mismatch")

    cost = result["cost"]
    cost_parts = [cost[k] for k in ("model", "tool", "other")]
    if _is_available(cost["total"]) and all(_is_available(x) for x in cost_parts):
        expected = sum(float(x["value"]) for x in cost_parts)
        if not _close(float(cost["total"]["value"]), expected, atol=1e-6):
            issues.append("cost_total_component_mismatch")

    tokens = result["token_usage"]
    if all(_is_available(tokens[k]) for k in ("input_tokens", "output_tokens", "total_tokens")):
        expected = int(tokens["input_tokens"]["value"]) + int(tokens["output_tokens"]["value"])
        if int(tokens["total_tokens"]["value"]) != expected:
            issues.append("token_total_component_mismatch")

    if cost["currency_availability"] in {"NOT_PROVIDED", "NOT_APPLICABLE"} and cost.get("currency") is not None:
        issues.append("cost_currency_present_when_unavailable")
    if cost["currency_availability"] in {"AVAILABLE", "ESTIMATED"} and not cost.get("currency"):
        issues.append("cost_currency_missing_when_available")

    timestamps = result["timestamps"]
    started = timestamps.get("started_at")
    finished = timestamps.get("finished_at")
    availability = timestamps.get("remote_availability")
    if availability in {"NOT_PROVIDED", "NOT_APPLICABLE"} and (started is not None or finished is not None):
        issues.append("remote_timestamps_present_when_unavailable")
    if availability in {"AVAILABLE", "ESTIMATED"} and (started is None or finished is None):
        issues.append("remote_timestamps_missing_when_available")
    if started and finished:
        try:
            sdt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            fdt = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
            if fdt < sdt:
                issues.append("timestamp_finished_before_started")
        except Exception:
            pass
    return issues


def _source_is_untrusted_for_live(value: Any) -> bool:
    text = str(value or "").lower()
    return any(word in text for word in ("fixture", "mock", "controlled_fault", "sandbox"))


def _validate_source_integrity(result: Mapping[str, Any]) -> None:
    """来源一致性门禁：LIVE不仅检查顶层，还检查指标、Tool Trace、Evidence与执行器类型。"""
    source = result["source"]
    provenance = result["provenance"]
    mode = result["run_mode"]
    kind = source["kind"]
    errors: list[str] = []

    if provenance["execution_id"] != result["run_id"]:
        errors.append("provenance_execution_id_mismatch")

    if mode == "LIVE":
        if kind not in {"BACKEND", "LIVE_CAPTURE"}:
            errors.append("live_requires_backend_or_live_capture_source")
        if source["is_fixture"] or source["is_mock"]:
            errors.append("live_source_cannot_be_fixture_or_mock")
        if source.get("fixture_reason"):
            errors.append("live_source_cannot_have_fixture_reason")
        for field in ("provider", "adapter_id"):
            if not source.get(field):
                errors.append(f"live_source_missing_{field}")
        if not provenance.get("source_endpoint"):
            errors.append("live_provenance_requires_source_endpoint")
        if provenance.get("environment") == "SANDBOX":
            errors.append("live_cannot_claim_sandbox_environment")
        if provenance.get("executor_type") != "LIVE_EXECUTOR":
            errors.append("live_requires_live_executor_type")
        if _source_is_untrusted_for_live(provenance.get("producer")):
            errors.append("live_payload_cannot_use_fixture_mock_or_sandbox_producer")
        if not (provenance.get("remote_execution_id") or provenance.get("raw_response_ref")):
            errors.append("live_requires_remote_execution_or_raw_response_reference")
        if provenance.get("raw_response_ref"):
            if not provenance.get("raw_response_source"):
                errors.append("live_raw_response_requires_source")
            elif _source_is_untrusted_for_live(provenance.get("raw_response_source")):
                errors.append("live_raw_response_source_cannot_be_fixture_mock_or_sandbox")
        if source.get("reference") and _source_is_untrusted_for_live(source.get("reference")):
            errors.append("live_source_reference_cannot_be_fixture_or_mock")

        metric_groups = [
            *(result["latency"][k] for k in ("total_ms", "model_ms", "tool_ms", "queue_ms")),
            *(result["cost"][k] for k in ("total", "model", "tool", "other")),
            *(result["token_usage"][k] for k in ("input_tokens", "output_tokens", "total_tokens", "cache_hit_tokens", "cache_miss_tokens")),
            result["quality_metrics"]["candidate_reported_score"],
        ]
        for metric in metric_groups:
            if metric.get("availability") in {"AVAILABLE", "ESTIMATED"}:
                if not metric.get("source"):
                    errors.append("live_available_metric_requires_source")
                elif _source_is_untrusted_for_live(metric.get("source")):
                    errors.append("live_metric_source_cannot_be_fixture_mock_or_sandbox")
        for call in result.get("tool_trace", []):
            call_source = call.get("source")
            if not call_source:
                errors.append("live_tool_trace_requires_source")
            elif _source_is_untrusted_for_live(call_source):
                errors.append("live_tool_trace_source_cannot_be_fixture_mock_or_sandbox")
            lm = call.get("latency_ms") or {}
            if lm.get("availability") in {"AVAILABLE", "ESTIMATED"} and _source_is_untrusted_for_live(lm.get("source")):
                errors.append("live_tool_trace_metric_source_cannot_be_fixture_mock_or_sandbox")
        for row in result.get("evidence", []):
            evidence_source = row.get("source")
            if not evidence_source:
                errors.append("live_evidence_requires_source")
            elif _source_is_untrusted_for_live(evidence_source):
                errors.append("live_evidence_source_cannot_be_fixture_mock_or_sandbox")
            if _source_is_untrusted_for_live(row.get("source_ref")):
                errors.append("live_evidence_cannot_reference_fixture_mock_or_sandbox")
        if result["timestamps"].get("remote_availability") == "AVAILABLE" and not provenance.get("remote_execution_id"):
            errors.append("live_remote_timestamps_require_remote_execution_id")

    elif mode == "FIXTURE":
        if kind != "FIXTURE" or not source["is_fixture"] or source["is_mock"]:
            errors.append("fixture_source_flags_invalid")
        if not source.get("fixture_reason"):
            errors.append("fixture_reason_required")
        if provenance.get("environment") != "SANDBOX" or provenance.get("executor_type") != "FIXTURE_EXECUTOR":
            errors.append("fixture_must_be_sandbox_fixture_executor")
    elif mode == "MOCK":
        if kind != "MOCK" or not source["is_fixture"] or not source["is_mock"]:
            errors.append("mock_source_flags_invalid")
        if provenance.get("environment") != "SANDBOX" or provenance.get("executor_type") != "MOCK_EXECUTOR":
            errors.append("mock_must_be_sandbox_mock_executor")
    elif mode == "CONTROLLED_FAULT":
        if kind != "CONTROLLED_FAULT" or not source["is_fixture"] or source["is_mock"]:
            errors.append("controlled_fault_source_flags_invalid")
        if not source.get("fixture_reason"):
            errors.append("controlled_fault_reason_required")
        if provenance.get("environment") != "SANDBOX" or provenance.get("executor_type") != "CONTROLLED_FAULT_EXECUTOR":
            errors.append("controlled_fault_must_be_sandbox_controlled_fault_executor")

    if errors:
        raise SchemaValidationError(";".join(sorted(set(errors))))


def validate_workflow_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_payload(payload, "workflow_result.schema.json")
    _validate_source_integrity(result)

    evidence_ids = [row["evidence_id"] for row in result["evidence"]]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise SchemaValidationError("duplicate_evidence_id")
    evidence_set = set(evidence_ids)
    root_refs = set(result["output"]["root_cause_evidence_refs"])
    if not root_refs.issubset(evidence_set):
        raise SchemaValidationError("root_cause_evidence_ref_not_found")
    for call in result["tool_trace"]:
        if not set(call["evidence_refs"]).issubset(evidence_set):
            raise SchemaValidationError(f"tool_trace_evidence_ref_not_found:{call['tool_call_id']}")

    integrity_issues = _validate_metric_integrity(result)
    if integrity_issues:
        raise SchemaValidationError(";".join(integrity_issues))
    return result


def validate_evaluation_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "evaluation_result.schema.json")


def validate_decision_card(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "decision_card.schema.json")


def validate_comparison_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate_payload(payload, "comparison_result.schema.json")


def validate_linked_inputs(task: Mapping[str, Any], candidate: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    validate_task_input(task)
    validate_candidate_plan(candidate)
    validate_experiment_spec(spec)
    expected = (task["task_id"], task["case_id"])
    if (candidate["task_id"], candidate["case_id"]) != expected:
        raise SchemaValidationError("candidate_task_or_case_id_mismatch")
    if (spec["task_id"], spec["case_id"]) != expected:
        raise SchemaValidationError("experiment_task_or_case_id_mismatch")
    if spec["candidate_id"] != candidate["candidate_id"]:
        raise SchemaValidationError("experiment_candidate_id_mismatch")
    task_tools = set(task["available_tools"])
    candidate_tools = set(candidate["tools"])
    required_tools = set(spec["required_tools"])
    if not candidate_tools.issubset(task_tools):
        raise SchemaValidationError("candidate_uses_tool_not_available_to_task")
    if not required_tools.issubset(task_tools):
        raise SchemaValidationError("experiment_requires_tool_not_available_to_task")
    if not required_tools.issubset(candidate_tools):
        raise SchemaValidationError("experiment_requires_tool_not_in_candidate")
