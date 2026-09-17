from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from experiment.policy_utils import parse_strict_bool
from experiment.schemas import utc_now, validate_workflow_result


class YuanqiMappingError(ValueError):
    pass


def _get_path(payload: Mapping[str, Any], path: str) -> Any:
    cur: Any = payload
    if not path:
        return cur
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            raise YuanqiMappingError(f"missing_source_path:{path}")
        cur = cur[part]
    return cur


def _get_optional(payload: Mapping[str, Any], path: str | None) -> Any:
    if not path:
        return None
    try:
        return _get_path(payload, path)
    except YuanqiMappingError:
        return None


def _parse_bool(value: Any, *, field_name: str, default: bool | None = None) -> bool | None:
    try:
        if value is None and default is None:
            return None
        return parse_strict_bool(value, field_name=field_name, default=default)
    except ValueError as exc:
        raise YuanqiMappingError(str(exc)) from exc


def _list_value(mapping: Mapping[str, Any], key: str, *, default: list[str] | None = None) -> list[str]:
    """缺失/null使用default；显式[]保持为空，不做falsey回退。"""
    if key not in mapping or mapping.get(key) is None:
        return list(default or [])
    value = mapping.get(key)
    if not isinstance(value, list):
        raise YuanqiMappingError(f"list_required:{key}")
    return [str(x) for x in value]


def _metric(value: Any, *, source: str, availability: str | None = None, note: str | None = None) -> dict[str, Any]:
    if availability in {"NOT_PROVIDED", "NOT_APPLICABLE"} or value is None:
        return {"value": None, "availability": availability or "NOT_PROVIDED", "source": source, "note": note}
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise YuanqiMappingError(f"metric_must_be_number:{source}")
    av = availability or "AVAILABLE"
    if av == "ESTIMATED" and not note:
        raise YuanqiMappingError("estimated_metric_requires_note")
    return {"value": value, "availability": av, "source": source, "note": note}


def _raw_ref(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _normalize_tool_trace(rows: Any, provider: str) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise YuanqiMappingError("tool_trace_must_be_list")
    out = []
    for idx, raw in enumerate(rows, start=1):
        if not isinstance(raw, Mapping):
            raise YuanqiMappingError("tool_trace_item_must_be_object")
        latency = raw.get("latency_ms")
        if isinstance(latency, Mapping):
            latency_metric = dict(latency)
            if latency_metric.get("availability") in {"AVAILABLE", "ESTIMATED"} and not latency_metric.get("source"):
                latency_metric["source"] = provider
        else:
            latency_metric = _metric(latency, source=provider)
        out.append({
            "tool_call_id": str(raw.get("tool_call_id") or f"remote-call-{idx}"),
            "tool": str(raw.get("tool") or "unknown_tool"),
            "status": str(raw.get("status") or "SKIPPED"),
            "arguments": dict(raw.get("arguments") or {}),
            "result": raw.get("result"),
            "error": raw.get("error"),
            "latency_ms": latency_metric,
            "retry_count": int(raw.get("retry_count") or 0),
            "evidence_refs": [str(x) for x in raw.get("evidence_refs") or []],
            "unauthorized_attempt": bool(_parse_bool(raw.get("unauthorized_attempt"), field_name="tool_trace.unauthorized_attempt", default=False)),
            "source": provider,
        })
    return out


def _normalize_evidence(rows: Any, case_id: str, provider: str) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise YuanqiMappingError("evidence_must_be_list")
    out = []
    for idx, raw in enumerate(rows, start=1):
        if not isinstance(raw, Mapping):
            raise YuanqiMappingError("evidence_item_must_be_object")
        out.append({
            "evidence_id": str(raw.get("evidence_id") or f"remote-evidence-{idx}"),
            "evidence_type": str(raw.get("evidence_type") or "OTHER"),
            "claim": str(raw.get("claim") or "未提供结构化claim"),
            "source_ref": str(raw.get("source_ref") or "remote:unmapped"),
            "support_level": str(raw.get("support_level") or "CONTEXT_ONLY"),
            "content": None if raw.get("content") is None else str(raw.get("content")),
            "claim_ids": [str(x) for x in raw.get("claim_ids") or []],
            "target": None if raw.get("target") is None else str(raw.get("target")),
            "action": None if raw.get("action") is None else str(raw.get("action")),
            "result": None if raw.get("result") is None else str(raw.get("result")),
            "source": provider,
        })
    return out


@dataclass(frozen=True)
class YuanqiFrontHalfMapping:
    """前半段字段映射模板；默认字段不代表腾讯元器官方JSON格式。"""
    requirement_path: str = "enterprise_requirement"
    candidates_path: str = "candidates"
    selected_candidate_id_path: str = "selected_candidate_id"
    experiment_params_path: str = "experiment_params"
    run_context_path: str = "run_context"


@dataclass(frozen=True)
class YuanqiResponseMapping:
    workflow_result_path: str | None = None
    paths: Mapping[str, str] = field(default_factory=dict)
    provider: str = "Tencent Yuanqi"


class YuanqiResponseAdapter:
    adapter_id = "yuanqi-response-adapter-v1.2-TEMPLATE_NOT_LIVE_VERIFIED"

    def __init__(self, mapping: YuanqiResponseMapping):
        if not mapping.workflow_result_path and not mapping.paths:
            raise YuanqiMappingError("yuanqi_response_mapping_required")
        self.mapping = mapping

    def parse(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.mapping.workflow_result_path:
            raise YuanqiMappingError("field_mapping_requires_execution_context")
        raw = _get_path(payload, self.mapping.workflow_result_path)
        if not isinstance(raw, Mapping):
            raise YuanqiMappingError("mapped_workflow_result_must_be_object")
        return validate_workflow_result(raw)

    def parse_with_context(self, payload: Mapping[str, Any], *, task: Mapping[str, Any], candidate: Mapping[str, Any], experiment_spec: Mapping[str, Any], run_id: str, source_endpoint: str) -> dict[str, Any]:
        if self.mapping.workflow_result_path:
            return self.parse(payload)
        p = dict(self.mapping.paths)
        required_paths = ["status", "output.final_action", "output.diagnosis_code", "output.response", "output.confidence"]
        missing_cfg = [k for k in required_paths if not p.get(k)]
        if missing_cfg:
            raise YuanqiMappingError("missing_required_mapping:" + ",".join(missing_cfg))

        def req(key: str) -> Any:
            return _get_path(payload, p[key])

        def opt(key: str) -> Any:
            return _get_optional(payload, p.get(key))

        provider = self.mapping.provider
        now = utc_now()
        cost_currency = opt("cost.currency")
        remote_run_id = opt("remote_execution_id")
        started_at = opt("timestamps.started_at")
        finished_at = opt("timestamps.finished_at")
        if (started_at is None) != (finished_at is None):
            raise YuanqiMappingError("remote_timestamps_must_be_both_present_or_both_missing")
        remote_time_availability = "AVAILABLE" if started_at is not None else "NOT_PROVIDED"
        environment = str(opt("environment") or "UNKNOWN").upper()
        if environment not in {"UNKNOWN", "LOCAL", "STAGING", "PRODUCTION"}:
            raise YuanqiMappingError("invalid_environment")

        tool_trace = _normalize_tool_trace(opt("tool_trace"), provider)
        evidence = _normalize_evidence(opt("evidence"), str(task["case_id"]), provider)
        raw_ref = _raw_ref(payload)
        source_reference = str(remote_run_id) if remote_run_id is not None else raw_ref
        result = {
            "schema_version": "2.2",
            "run_id": run_id,
            "case_id": task["case_id"],
            "candidate_id": candidate["candidate_id"],
            "experiment_id": experiment_spec["experiment_id"],
            "status": str(req("status")),
            "source": {"kind": "LIVE_CAPTURE", "provider": provider, "adapter_id": self.adapter_id, "reference": source_reference, "is_fixture": False, "is_mock": False, "fixture_reason": None},
            "run_mode": "LIVE",
            "output": {
                "final_action": str(req("output.final_action")),
                "diagnosis_code": str(req("output.diagnosis_code")),
                "response": str(req("output.response")),
                "root_cause": opt("output.root_cause"),
                "confidence": str(req("output.confidence")),
                "handoff_type": opt("output.handoff_type"),
                "guardrail_blocked": bool(_parse_bool(opt("output.guardrail_blocked"), field_name="output.guardrail_blocked", default=False)),
                "guardrail_triggered": bool(_parse_bool(opt("output.guardrail_triggered"), field_name="output.guardrail_triggered", default=False)),
                "root_cause_evidence_refs": list(opt("output.root_cause_evidence_refs") or []),
                "checks": dict(opt("output.checks") or {}),
            },
            "quality_metrics": {
                "candidate_reported_task_success": _parse_bool(opt("quality_metrics.candidate_reported_task_success"), field_name="quality_metrics.candidate_reported_task_success", default=None),
                "candidate_reported_score": _metric(opt("quality_metrics.candidate_reported_score"), source=provider),
                "metric_breakdown": dict(opt("quality_metrics.metric_breakdown") or {}),
            },
            "latency": {k: _metric(opt(f"latency.{k}"), source=provider) for k in ("total_ms", "model_ms", "tool_ms", "queue_ms")},
            "cost": {
                "currency": str(cost_currency) if cost_currency is not None else None,
                "currency_availability": "AVAILABLE" if cost_currency is not None else "NOT_PROVIDED",
                **{k: _metric(opt(f"cost.{k}"), source=provider) for k in ("total", "model", "tool", "other")},
            },
            "token_usage": {k: _metric(opt(f"token_usage.{k}"), source=provider) for k in ("input_tokens", "output_tokens", "total_tokens", "cache_hit_tokens", "cache_miss_tokens")},
            "tool_trace": tool_trace,
            "errors": list(opt("errors") or []),
            "evidence": evidence,
            "provenance": {
                "execution_id": run_id,
                "producer": "yuanqi_live_executor",
                "adapter_id": self.adapter_id,
                "source_endpoint": source_endpoint,
                "captured_at": now,
                "environment": environment,
                "raw_response_ref": raw_ref,
                "raw_response_source": provider,
                "executor_type": "LIVE_EXECUTOR",
                "remote_execution_id": None if remote_run_id is None else str(remote_run_id),
            },
            "timestamps": {
                "started_at": None if started_at is None else str(started_at),
                "finished_at": None if finished_at is None else str(finished_at),
                "remote_availability": remote_time_availability,
                "received_at": now,
            },
        }
        return validate_workflow_result(result)


def prepare_run_requests(payload: Mapping[str, Any], mapping: YuanqiFrontHalfMapping | None = None) -> dict[str, Any]:
    """元器前半段payload → 平台无关RunRequest。

    默认模板仅用于联调；真实字段路径必须在LIVE时确认。
    """
    mapping = mapping or YuanqiFrontHalfMapping()
    requirement = _get_path(payload, mapping.requirement_path)
    candidates = _get_path(payload, mapping.candidates_path)
    params = _get_path(payload, mapping.experiment_params_path)
    run_context_raw = _get_optional(payload, mapping.run_context_path) or {}
    if not isinstance(candidates, list) or not candidates:
        raise YuanqiMappingError("candidates_must_be_nonempty_list")
    if not isinstance(requirement, Mapping) or not isinstance(params, Mapping) or not isinstance(run_context_raw, Mapping):
        raise YuanqiMappingError("requirement_params_or_run_context_must_be_object")

    case_id = str(requirement.get("case_id") or f"yuanqi-live-{hashlib.sha256(str(requirement).encode()).hexdigest()[:10]}")
    task_id = str(requirement.get("task_id") or f"task-{case_id}")
    all_tools: list[str] = []
    for row in candidates:
        if not isinstance(row, Mapping):
            raise YuanqiMappingError("candidate_item_must_be_object")
        all_tools.extend(str(x) for x in row.get("tools", []))
    raw_available_tools = _list_value(requirement, "available_tools", default=all_tools)
    task = {
        "schema_version": "2.1",
        "task_id": task_id,
        "case_id": case_id,
        "user_query": str(requirement.get("user_query") or requirement.get("description") or ""),
        "visible_context": dict(requirement.get("visible_context") or {}),
        "available_docs": list(requirement.get("available_docs") or []),
        "available_tools": list(dict.fromkeys(raw_available_tools)),
        "safety_constraints": dict(requirement.get("safety_constraints") or {"allow_write_operations": False, "require_evidence_for_dynamic_claims": True, "prohibited_operations": ["unauthorized_write"]}),
        "business_constraints": dict(requirement.get("business_constraints") or {}),
        "metadata": {"source_dataset": None, "source_ref": None, "platform_hint": "腾讯元器（待真实字段联调）", "notes": "字段映射模板，不代表元器官方JSON格式。"},
        "created_at": None,
    }

    mode = str(run_context_raw.get("mode") or "LIVE_POC").upper()
    if mode not in {"LIVE_POC", "BENCHMARK"}:
        raise YuanqiMappingError("unsupported_run_context_mode")
    raw_success_criteria = params.get("success_criteria")
    if raw_success_criteria is None:
        if mode == "LIVE_POC":
            raise YuanqiMappingError("live_poc_requires_explicit_success_criteria")
        raw_success_criteria = {"min_quality_score": 0.8, "max_latency_ms": 5000, "max_cost": 0.5, "cost_currency": "CNY", "require_tool_trace": True, "require_evidence": True, "max_error_count": 0}
    if not isinstance(raw_success_criteria, Mapping):
        raise YuanqiMappingError("success_criteria_must_be_object")

    common_required_tools = _list_value(params, "required_tools", default=[])
    raw_by_candidate = params.get("required_tools_by_candidate")
    if raw_by_candidate is None:
        by_candidate = {}
    elif isinstance(raw_by_candidate, Mapping):
        by_candidate = dict(raw_by_candidate)
    else:
        raise YuanqiMappingError("required_tools_by_candidate_must_be_object")
    base_experiment_id = str(params.get("experiment_id") or params.get("experiment_id_prefix") or f"exp-{case_id}")
    out_candidates: list[dict[str, Any]] = []
    specs: list[dict[str, Any]] = []
    for idx, row in enumerate(candidates, start=1):
        cid = str(row.get("candidate_id") or f"candidate-{idx}")
        candidate = {
            "schema_version": "2.1", "candidate_id": cid, "task_id": task_id, "case_id": case_id,
            "name": str(row.get("name") or cid), "approach_type": str(row.get("approach_type") or "FIXED_TOOL_WORKFLOW"),
            "summary": str(row.get("summary") or "腾讯元器前半段候选方案"), "model_provider": row.get("model_provider"), "model_name": row.get("model_name"),
            "tools": list(row.get("tools") or []), "assumptions": list(row.get("assumptions") or []), "expected_strengths": list(row.get("expected_strengths") or []),
            "expected_risks": list(row.get("expected_risks") or []), "estimated": row.get("estimated"),
            "metadata": {"source_dataset": None, "source_ref": None, "platform_hint": "腾讯元器（待真实字段联调）", "notes": "字段映射模板。"},
        }
        sc = dict(raw_success_criteria)
        for bool_key in ("require_tool_trace", "require_evidence"):
            if bool_key not in sc:
                raise YuanqiMappingError(f"success_criteria_missing:{bool_key}")
            sc[bool_key] = bool(_parse_bool(sc[bool_key], field_name=f"success_criteria.{bool_key}"))
        if cid in by_candidate:
            raw_required = by_candidate[cid]
            if raw_required is None:
                required_tools = []
            elif isinstance(raw_required, list):
                required_tools = [str(x) for x in raw_required]
            else:
                raise YuanqiMappingError(f"required_tools_by_candidate_must_be_list:{cid}")
        else:
            required_tools = list(common_required_tools)
        experiment_id = base_experiment_id if len(candidates) == 1 else f"{base_experiment_id}-{cid}"
        profile = (params.get("simulation_profiles_by_candidate") or {}).get(cid)
        spec = {
            "schema_version": "2.1", "experiment_id": experiment_id, "task_id": task_id, "case_id": case_id, "candidate_id": cid,
            "execution_mode": str(params.get("execution_mode") or "LIVE"), "objective": str(params.get("objective") or "验证候选方案是否满足业务阈值"),
            "success_criteria": sc, "required_tools": required_tools, "prohibited_tools": list(params.get("prohibited_tools") or ["unauthorized_write"]),
            "simulation": {"profile": profile, "seed": params.get("seed")}, "business_constraints": dict(params.get("business_constraints") or {}),
            "repeats": int(1 if params.get("repeats") is None else params.get("repeats")), "created_at": None,
        }
        out_candidates.append(candidate)
        specs.append(spec)

    run_context: dict[str, Any] = {
        "mode": mode,
        "comparison_rules": dict(run_context_raw.get("comparison_rules") or {}),
    }
    if mode == "LIVE_POC":
        acceptance = run_context_raw.get("live_acceptance_contract") or params.get("acceptance_contract")
        if not isinstance(acceptance, Mapping):
            raise YuanqiMappingError("live_poc_requires_acceptance_contract")
        run_context["live_acceptance_contract"] = dict(acceptance)
    elif mode == "BENCHMARK":
        run_context["live_acceptance_contract"] = None
    else:
        raise YuanqiMappingError("unsupported_run_context_mode")
    return {"task": task, "candidates": out_candidates, "experiment_specs": specs, "run_context": run_context}


def prepare_run_request(payload: Mapping[str, Any], mapping: YuanqiFrontHalfMapping | None = None) -> dict[str, Any]:
    all_rows = prepare_run_requests(payload, mapping)
    mapping = mapping or YuanqiFrontHalfMapping()
    selected_id = str(_get_path(payload, mapping.selected_candidate_id_path))
    for cand, spec in zip(all_rows["candidates"], all_rows["experiment_specs"]):
        if cand["candidate_id"] == selected_id:
            return {"task": all_rows["task"], "candidate": cand, "experiment_spec": spec, "run_context": all_rows["run_context"]}
    raise YuanqiMappingError("selected_candidate_not_found")
