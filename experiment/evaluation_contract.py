from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from .policy_utils import classify_business_constraints, normalize_list_field, parse_strict_bool
from .schemas import utc_now, validate_evaluation_contract

_SPECIAL_ASSERTIONS = {
    "should_escalate",
    "unsupported_root_cause",
    "evidence_sufficient",
    "unauthorized_action",
}


def _parse_acceptance_flags(text: str | None) -> dict[str, bool]:
    """仅从Private Gold显式(machine-readable) flag=true/false片段提取规则。"""
    if not text:
        return {}
    out: dict[str, bool] = {}
    for key, raw in re.findall(r"[（(]([A-Za-z0-9_]+)[）)]\s*=\s*(true|false)", text, flags=re.I):
        out[key] = raw.lower() == "true"
    return out


def _tool_policy(payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    """区分 allowed_tools 未提供/null、显式空列表、白名单三种语义。"""
    if "allowed_tools" not in payload or payload.get("allowed_tools") is None:
        return "UNRESTRICTED", []
    allowed = normalize_list_field(payload, "allowed_tools")
    return ("NONE_ALLOWED" if not allowed else "ALLOWLIST"), allowed


def _allowed_actions(payload: Mapping[str, Any]) -> list[str]:
    """缺失/null使用默认Action；显式[]表示NONE_ALLOWED。"""
    return normalize_list_field(
        payload,
        "allowed_actions",
        missing_default=["ANSWER", "CLARIFY", "HANDOFF", "REFUSE"],
    )


def _required_tools(payload: Mapping[str, Any]) -> list[str]:
    """缺失/null/[]均表示没有强制工具要求；不回退到候选工具。"""
    return normalize_list_field(payload, "required_tools", missing_default=[])


def _empty_decision_criteria(source: str = "NOT_PROVIDED") -> dict[str, Any]:
    return {
        "source": source,
        "quality": {"status": "NOT_PROVIDED", "min_score": None},
        "cost": {"status": "NOT_PROVIDED", "max_value": None, "currency": None},
        "latency": {"status": "NOT_PROVIDED", "max_ms": None},
    }


def _normalize_live_decision_criteria(payload: Mapping[str, Any]) -> dict[str, Any]:
    if parse_strict_bool(payload.get("demo_default"), field_name="demo_default", default=False) or parse_strict_bool(
        payload.get("template_only"), field_name="template_only", default=False
    ):
        raise ValueError("demo_default_not_allowed_for_live_decision")

    raw = payload.get("decision_criteria")
    if not isinstance(raw, Mapping):
        raise ValueError("insufficient_acceptance_criteria:decision_criteria_required")

    quality = raw.get("quality")
    cost = raw.get("cost")
    latency = raw.get("latency")
    if not isinstance(quality, Mapping) or not isinstance(cost, Mapping) or not isinstance(latency, Mapping):
        raise ValueError("insufficient_acceptance_criteria:quality_cost_latency_required")

    q_status = str(quality.get("status") or "").upper()
    if q_status != "REQUIRED" or not isinstance(quality.get("min_score"), (int, float)) or isinstance(quality.get("min_score"), bool):
        raise ValueError("insufficient_acceptance_criteria:quality_target_required")
    q_value = float(quality["min_score"])
    if not 0 <= q_value <= 1:
        raise ValueError("invalid_acceptance_quality_target")

    cost_status = str(cost.get("status") or "").upper()
    if cost_status not in {"REQUIRED", "NOT_APPLICABLE"}:
        raise ValueError("insufficient_acceptance_criteria:cost_must_be_required_or_not_applicable")
    if cost_status == "REQUIRED":
        if not isinstance(cost.get("max_value"), (int, float)) or isinstance(cost.get("max_value"), bool) or float(cost["max_value"]) < 0:
            raise ValueError("invalid_acceptance_cost_target")
        if not str(cost.get("currency") or "").strip():
            raise ValueError("acceptance_cost_currency_required")
        cost_out = {"status": "REQUIRED", "max_value": float(cost["max_value"]), "currency": str(cost["currency"])}
    else:
        cost_out = {"status": "NOT_APPLICABLE", "max_value": None, "currency": None}

    latency_status = str(latency.get("status") or "").upper()
    if latency_status not in {"REQUIRED", "NOT_APPLICABLE"}:
        raise ValueError("insufficient_acceptance_criteria:latency_must_be_required_or_not_applicable")
    if latency_status == "REQUIRED":
        if not isinstance(latency.get("max_ms"), (int, float)) or isinstance(latency.get("max_ms"), bool) or float(latency["max_ms"]) < 0:
            raise ValueError("invalid_acceptance_latency_target")
        latency_out = {"status": "REQUIRED", "max_ms": float(latency["max_ms"])}
    else:
        latency_out = {"status": "NOT_APPLICABLE", "max_ms": None}

    source = str(raw.get("source") or "").strip().upper()
    allowed_sources = {"USER_CONFIRMED", "BUSINESS_CONFIRMED"}
    known_untrusted = {"SYSTEM_TEMPLATE", "DEMO_DEFAULT", "TEMPLATE_ONLY", "NOT_PROVIDED"}
    if not source:
        raise ValueError("insufficient_acceptance_criteria:decision_criteria_source_required")
    if source in known_untrusted:
        raise ValueError(f"insufficient_acceptance_criteria:untrusted_decision_criteria_source:{source}")
    if source not in allowed_sources:
        raise ValueError(f"invalid_decision_criteria_source:{source}")

    return {
        "source": source,
        "quality": {"status": "REQUIRED", "min_score": q_value},
        "cost": cost_out,
        "latency": latency_out,
    }


def compile_private_gold(case_id: str, gold: Mapping[str, Any]) -> dict[str, Any]:
    expected = deepcopy(dict(gold.get("expected") or {}))
    flags = _parse_acceptance_flags(str(gold.get("acceptance_criteria") or ""))

    required_checks = {k: v for k, v in flags.items() if k not in _SPECIAL_ASSERTIONS}
    if "should_escalate" in flags:
        expected["should_escalate"] = flags["should_escalate"]

    expected_evidence_sufficient = flags.get("evidence_sufficient")
    if flags.get("unsupported_root_cause") is False:
        expected["root_cause_must_be_evidenced"] = True
    if flags.get("unauthorized_action") is False:
        expected.setdefault("forbidden_claims", []).append("UNAUTHORIZED_ACTION")

    evidence_keywords = [str(x) for x in expected.get("evidence_keywords") or []]
    evidence_required = parse_strict_bool(expected.get("evidence_required"), field_name="gold.evidence_required", default=False)
    tool_policy_mode, allowed_tools = _tool_policy(expected)
    evidence_requirements = {
        "required_types": list(expected.get("required_evidence_types") or []),
        "required_claim_ids": list(expected.get("required_claim_ids") or []),
        "required_targets": list(expected.get("required_evidence_targets") or [case_id]),
        "require_tool_link": parse_strict_bool(expected.get("evidence_required"), field_name="gold.evidence_required", default=True),
        "require_action_result": parse_strict_bool(expected.get("evidence_required"), field_name="gold.evidence_required", default=True),
    }

    contract = {
        "schema_version": "1.2",
        "contract_id": f"gold-{case_id}",
        "case_id": case_id,
        "source": "PRIVATE_GOLD",
        "frozen_at": utc_now(),
        "allowed_actions": _allowed_actions(expected),
        "accepted_diagnoses": list(expected.get("accepted_diagnoses") or []),
        "required_tools": _required_tools(expected),
        "allowed_tools": allowed_tools,
        "tool_policy_mode": tool_policy_mode,
        "forbidden_tools": list(expected.get("forbidden_tools") or []),
        "evidence_required": evidence_required,
        "should_escalate": parse_strict_bool(expected.get("should_escalate"), field_name="gold.should_escalate", default=False),
        "guardrail_required": parse_strict_bool(expected.get("guardrail_required"), field_name="gold.guardrail_required", default=False),
        "root_cause_must_be_evidenced": parse_strict_bool(expected.get("root_cause_must_be_evidenced"), field_name="gold.root_cause_must_be_evidenced", default=True),
        "required_response_keywords": list(expected.get("required_response_keywords") or []),
        "required_checks": required_checks,
        "forbidden_claims": list(expected.get("forbidden_claims") or []),
        "evidence_requirements": evidence_requirements,
        "expected_evidence_sufficient": expected_evidence_sufficient,
        "decision_criteria": _empty_decision_criteria("BENCHMARK_PRIVATE_GOLD"),
        "safety_policy": {"allow_write_operations": None, "require_evidence_for_dynamic_claims": False, "prohibited_operations": []},
        "business_constraints": {},
        "notes": (
            "Private Gold编译。历史evidence_keywords仅作人工参考，不再作为单关键词充分性规则。"
            + (f" legacy_evidence_keywords={evidence_keywords}" if evidence_keywords else "")
        ),
    }
    return validate_evaluation_contract(contract)


def compile_live_acceptance(case_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """冻结LIVE_POC运行前业务验收标准；缺少实质标准时拒绝正式决策。"""
    for required_flag in ("evidence_required", "should_escalate", "guardrail_required"):
        if required_flag not in payload:
            raise ValueError(f"insufficient_acceptance_criteria:{required_flag}_must_be_explicit")
    decision_criteria = _normalize_live_decision_criteria(payload)
    tool_policy_mode, allowed_tools = _tool_policy(payload)
    evidence_required = parse_strict_bool(payload.get("evidence_required"), field_name="evidence_required")
    er = payload.get("evidence_requirements") or {}
    if not isinstance(er, Mapping):
        raise ValueError("evidence_requirements_must_be_object")

    contract = {
        "schema_version": "1.2",
        "contract_id": str(payload.get("contract_id") or f"live-{case_id}"),
        "case_id": case_id,
        "source": "LIVE_ACCEPTANCE_CONTRACT",
        "frozen_at": str(payload.get("frozen_at") or utc_now()),
        "allowed_actions": _allowed_actions(payload),
        "accepted_diagnoses": list(payload.get("accepted_diagnoses") or []),
        "required_tools": _required_tools(payload),
        "allowed_tools": allowed_tools,
        "tool_policy_mode": tool_policy_mode,
        "forbidden_tools": list(payload.get("forbidden_tools") or []),
        "evidence_required": evidence_required,
        "should_escalate": parse_strict_bool(payload.get("should_escalate"), field_name="should_escalate"),
        "guardrail_required": parse_strict_bool(payload.get("guardrail_required"), field_name="guardrail_required"),
        "root_cause_must_be_evidenced": parse_strict_bool(payload.get("root_cause_must_be_evidenced"), field_name="root_cause_must_be_evidenced", default=True),
        "required_response_keywords": list(payload.get("required_response_keywords") or []),
        "required_checks": dict(payload.get("required_checks") or {}),
        "forbidden_claims": list(payload.get("forbidden_claims") or []),
        "evidence_requirements": {
            "required_types": list(er.get("required_types") or []),
            "required_claim_ids": list(er.get("required_claim_ids") or []),
            "required_targets": list(er.get("required_targets") or [case_id]),
            "require_tool_link": parse_strict_bool(er.get("require_tool_link"), field_name="evidence_requirements.require_tool_link", default=evidence_required),
            "require_action_result": parse_strict_bool(er.get("require_action_result"), field_name="evidence_requirements.require_action_result", default=evidence_required),
        },
        "expected_evidence_sufficient": payload.get("expected_evidence_sufficient"),
        "decision_criteria": decision_criteria,
        "safety_policy": {"allow_write_operations": None, "require_evidence_for_dynamic_claims": False, "prohibited_operations": []},
        "business_constraints": {},
        "notes": str(payload.get("notes") or "LIVE_POC运行前冻结的业务验收契约。"),
    }
    return validate_evaluation_contract(contract)


def merge_evaluation_contract(
    task: Mapping[str, Any], experiment_spec: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    """将Task、Experiment与EvaluationContract合并为Evaluator实际消费的严格策略。

    布尔约束采用更严格者优先：任一层要求Evidence则最终要求Evidence；Task安全约束不需要上游重复复制。
    """
    out = deepcopy(validate_evaluation_contract(contract))
    task_safety = dict(task.get("safety_constraints") or {})
    spec_criteria = dict(experiment_spec.get("success_criteria") or {})

    task_requires_evidence = parse_strict_bool(
        task_safety.get("require_evidence_for_dynamic_claims"),
        field_name="task.safety_constraints.require_evidence_for_dynamic_claims",
        default=False,
    )
    spec_requires_evidence = parse_strict_bool(
        spec_criteria.get("require_evidence"), field_name="experiment_spec.success_criteria.require_evidence", default=False
    )
    final_evidence_required = bool(out["evidence_required"] or task_requires_evidence or spec_requires_evidence)
    out["evidence_required"] = final_evidence_required
    if final_evidence_required:
        out["evidence_requirements"]["require_tool_link"] = True
        out["evidence_requirements"]["require_action_result"] = True

    allow_write = parse_strict_bool(
        task_safety.get("allow_write_operations"), field_name="task.safety_constraints.allow_write_operations", default=True
    )
    prohibited_ops = list(dict.fromkeys([str(x) for x in task_safety.get("prohibited_operations") or []]))
    out["safety_policy"] = {
        "allow_write_operations": allow_write,
        "require_evidence_for_dynamic_claims": task_requires_evidence,
        "prohibited_operations": prohibited_ops,
    }
    # 实验禁止工具与契约禁止工具都进入硬门禁；Task prohibited_operations由Evaluator按tool/action双通道检查。
    out["forbidden_tools"] = list(dict.fromkeys([*out["forbidden_tools"], *[str(x) for x in experiment_spec.get("prohibited_tools") or []]]))
    task_bc_raw = deepcopy(dict(task.get("business_constraints") or {}))
    experiment_bc_raw = deepcopy(dict(experiment_spec.get("business_constraints") or {}))
    task_bc = classify_business_constraints(task_bc_raw, scope="task")
    experiment_bc = classify_business_constraints(experiment_bc_raw, scope="experiment")
    out["business_constraints"] = {
        "task": task_bc_raw,
        "experiment": experiment_bc_raw,
        "supported": {"task": task_bc["supported"], "experiment": experiment_bc["supported"]},
        "informational_only": {"task": task_bc["informational_only"], "experiment": experiment_bc["informational_only"]},
        "unsupported_mandatory": {
            "task": task_bc["unsupported_mandatory"],
            "experiment": experiment_bc["unsupported_mandatory"],
        },
    }
    return validate_evaluation_contract(out)
