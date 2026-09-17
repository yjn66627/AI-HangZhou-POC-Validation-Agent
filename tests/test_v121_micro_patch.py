from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.adapters.yuanqi import YuanqiMappingError, prepare_run_requests
from backend.schemas import RunRequest
from experiment.case_registry import CaseRegistry
from experiment.evaluation_contract import compile_live_acceptance
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment
from experiment.pipeline import compare_candidates
from tools.audit_contract_field_usage import audit

ROOT = Path(__file__).resolve().parents[1]


def bundle() -> dict:
    return json.loads((ROOT / "examples" / "fx-success_bundle.json").read_text(encoding="utf-8"))


def acceptance(case_id: str, **overrides) -> dict:
    out = {
        "contract_id": f"v121-{case_id}",
        "allowed_actions": ["ANSWER"],
        "accepted_diagnoses": ["TASK_COMPLETED"],
        "required_tools": ["retrieve_context"],
        "allowed_tools": ["retrieve_context"],
        "forbidden_tools": ["write_resource"],
        "evidence_required": True,
        "should_escalate": False,
        "guardrail_required": False,
        "root_cause_must_be_evidenced": True,
        "decision_criteria": {
            "source": "BUSINESS_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": 0.8},
            "cost": {"status": "REQUIRED", "max_value": 0.5, "currency": "CNY"},
            "latency": {"status": "REQUIRED", "max_ms": 5000},
        },
        "required_response_keywords": [],
        "required_checks": {},
        "forbidden_claims": [],
        "evidence_requirements": {
            "required_types": [], "required_claim_ids": [], "required_targets": [case_id],
            "require_tool_link": True, "require_action_result": True,
        },
    }
    out.update(overrides)
    return out


def no_evidence(workflow: dict) -> dict:
    w = deepcopy(workflow)
    w["evidence"] = []
    w["output"]["root_cause"] = None
    w["output"]["root_cause_evidence_refs"] = []
    for row in w["tool_trace"]:
        row["evidence_refs"] = []
    return w


def add_success_tool(workflow: dict, tool: str, *, arguments=None) -> dict:
    w = deepcopy(workflow)
    row = deepcopy(w["tool_trace"][0])
    row.update({"tool_call_id": f"extra-{tool}", "tool": tool, "status": "SUCCESS", "arguments": arguments or {}, "evidence_refs": [], "unauthorized_attempt": False})
    w["tool_trace"].append(row)
    return w


def summary(cid: str, cost: float, currency: str, latency: float = 300.0) -> dict:
    return {
        "candidate_id": cid, "repeat_count": 3, "pass_rate": 1.0,
        "quality_mean": 0.9, "quality_std": 0.0, "failure_rate": 0.0,
        "timeout_rate": 0.0, "evidence_sufficiency_rate": 1.0,
        "latency_mean_ms": latency, "latency_p95_ms": latency, "latency_available_rate": 1.0,
        "cost_mean": cost, "cost_total": cost * 3, "cost_currency": currency, "cost_available_rate": 1.0,
        "tool_error_count": 0, "safety_block_count": 0, "safety_violation_count": 0,
        "human_review_count": 0, "mandatory_escalation_count": 0, "terminal_failure_count": 0, "execution_plan_violation_count": 0,
        "decision_counts": {"SUPPORT_CONTROLLED_TRIAL": 3}, "eligible": True, "ineligibility_reasons": [],
    }


# 1-3 严格布尔解析
def test_live_false_string_is_false():
    c = compile_live_acceptance("BOOL", acceptance("BOOL", evidence_required="false", should_escalate="FALSE", guardrail_required="false"))
    assert c["evidence_required"] is False and c["should_escalate"] is False and c["guardrail_required"] is False


def test_live_true_uppercase_is_true():
    c = compile_live_acceptance("BOOL", acceptance("BOOL", should_escalate="TRUE"))
    assert c["should_escalate"] is True


def test_invalid_boolean_is_rejected():
    with pytest.raises(ValueError, match="invalid_boolean"):
        compile_live_acceptance("BOOL", acceptance("BOOL", evidence_required="maybe"))


# 4-7 Evidence更严格者优先
def test_experiment_require_evidence_overrides_contract_false():
    b = bundle(); b["task"]["safety_constraints"]["require_evidence_for_dynamic_claims"] = False
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], evidence_required=False))
    w = no_evidence(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="ev-exp"))
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert e["evidence"]["status"] == "INSUFFICIENT" and e["passed"] is False


def test_task_require_evidence_overrides_experiment_and_contract_false():
    b = bundle(); b["experiment_spec"]["success_criteria"]["require_evidence"] = False
    b["task"]["safety_constraints"]["require_evidence_for_dynamic_claims"] = True
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], evidence_required=False))
    w = no_evidence(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="ev-task"))
    assert evaluate(w, c, b["experiment_spec"], b["task"])["evidence"]["status"] == "INSUFFICIENT"


def test_benchmark_gold_evidence_requirement_survives():
    b = bundle(); b["experiment_spec"]["success_criteria"]["require_evidence"] = False
    b["task"]["safety_constraints"]["require_evidence_for_dynamic_claims"] = False
    c = CaseRegistry().build_evaluation_contract(b["task"]["case_id"])
    w = no_evidence(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="ev-gold"))
    assert evaluate(w, c, b["experiment_spec"], b["task"])["evidence"]["status"] == "INSUFFICIENT"


def test_evidence_not_required_when_all_sources_false():
    b = bundle(); b["experiment_spec"]["success_criteria"]["require_evidence"] = False
    b["task"]["safety_constraints"]["require_evidence_for_dynamic_claims"] = False
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], evidence_required=False))
    w = no_evidence(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="ev-none"))
    assert evaluate(w, c, b["experiment_spec"], b["task"])["evidence"]["status"] == "NOT_REQUIRED"


# 8-10 Task安全约束真正进入Evaluator
def test_task_prohibited_tool_without_experiment_duplication_is_hard_gate():
    b = bundle(); b["task"]["safety_constraints"]["prohibited_operations"] = ["danger_tool"]
    b["experiment_spec"]["prohibited_tools"] = []
    w = add_success_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="task-prohibit"), "danger_tool")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], allowed_tools=None))
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert e["safety"]["violation"] is True and any("task_prohibited_operation_executed" in x for x in e["safety"]["violation_reasons"])


def test_task_disallow_write_blocks_successful_write():
    b = bundle(); b["experiment_spec"]["prohibited_tools"] = []
    w = add_success_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="task-write"), "write_resource")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], allowed_tools=None, forbidden_tools=[]))
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert any("task_write_operation_executed" in x for x in e["safety"]["violation_reasons"])


def test_task_business_quality_constraint_is_consumed():
    b = bundle(); b["task"]["business_constraints"]["min_quality_score"] = 1.0
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"]))
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="task-business")
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert e["quality"]["threshold"] == 1.0


# 11-15 LIVE Acceptance实质性
def test_live_acceptance_notes_only_rejected():
    with pytest.raises(ValueError, match="insufficient_acceptance_criteria"):
        compile_live_acceptance("LIVE-NOTES", {"notes": "仅说明"})


def test_live_acceptance_missing_quality_rejected():
    p = acceptance("LIVE-Q")
    p["decision_criteria"]["quality"] = {"status": "NOT_PROVIDED", "min_score": None}
    with pytest.raises(ValueError, match="quality_target_required"):
        compile_live_acceptance("LIVE-Q", p)


def test_live_acceptance_cost_not_applicable_is_valid():
    p = acceptance("LIVE-NA")
    p["decision_criteria"]["cost"] = {"status": "NOT_APPLICABLE", "max_value": None, "currency": None}
    c = compile_live_acceptance("LIVE-NA", p)
    assert c["decision_criteria"]["cost"]["status"] == "NOT_APPLICABLE"


def test_demo_default_cannot_drive_live_decision():
    with pytest.raises(ValueError, match="demo_default_not_allowed"):
        compile_live_acceptance("LIVE-DEMO", acceptance("LIVE-DEMO", demo_default=True))


def test_complete_live_acceptance_compiles():
    c = compile_live_acceptance("LIVE-FULL", acceptance("LIVE-FULL"))
    assert c["source"] == "LIVE_ACCEPTANCE_CONTRACT" and c["decision_criteria"]["quality"]["min_score"] == 0.8


# 16-18 跨币种Comparison
def test_cross_currency_without_fx_does_not_use_raw_cost():
    result = compare_candidates("FX", [{"aggregate": summary("z-usd", 0.10, "USD")}, {"aggregate": summary("a-cny", 0.20, "CNY")}])
    assert result["cost_comparison_status"] == "COST_NOT_COMPARABLE"
    assert result["recommended_candidate_id"] == "a-cny"  # 由确定性tie-breaker，不是0.10<0.20
    assert "不使用跨币种裸成本" in " ".join(result["rationale"])


def test_same_currency_cost_sorting_still_works():
    result = compare_candidates("FX", [{"aggregate": summary("expensive", 0.49, "CNY")}, {"aggregate": summary("cheap", 0.01, "CNY")}])
    assert result["cost_comparison_status"] == "SAME_CURRENCY" and result["recommended_candidate_id"] == "cheap"


def test_static_fx_conversion_enables_cost_comparison():
    result = compare_candidates("FX", [{"aggregate": summary("usd", 0.10, "USD")}, {"aggregate": summary("cny", 0.20, "CNY")}], comparison_rules={"base_currency": "CNY", "fx_rates": {"USD": 7.0}})
    assert result["cost_comparison_status"] == "STATIC_FX" and result["recommended_candidate_id"] == "cny"


# 19-22 allowed_tools三态 + 未授权
def test_allowed_tools_unspecified_means_unrestricted():
    c = compile_live_acceptance("TOOLS", acceptance("TOOLS", allowed_tools=None, required_tools=[]))
    assert c["tool_policy_mode"] == "UNRESTRICTED"


def test_allowed_tools_empty_means_none_allowed():
    c = compile_live_acceptance("TOOLS", acceptance("TOOLS", allowed_tools=[], required_tools=[]))
    assert c["tool_policy_mode"] == "NONE_ALLOWED"


def test_allowed_tools_allowlist_mode():
    c = compile_live_acceptance("TOOLS", acceptance("TOOLS", allowed_tools=["retrieve_context"]))
    assert c["tool_policy_mode"] == "ALLOWLIST"


def test_unlisted_tool_is_unexpected_under_allowlist():
    b = bundle(); b["experiment_spec"]["prohibited_tools"] = []
    w = add_success_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="allowlist"), "other_tool")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], allowed_tools=["retrieve_context"], forbidden_tools=[]))
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert "other_tool" in e["tool_trace"]["unexpected_tools"] and e["passed"] is False


# 23-25 API/Pydantic严格布尔、字段审计、部署文档
def test_pydantic_rejects_invalid_boolean():
    b = bundle()
    payload = {"task": b["task"], "candidate": b["candidate"], "experiment_spec": b["experiment_spec"], "run_context": {"mode": "BENCHMARK"}}
    payload["task"]["safety_constraints"]["allow_write_operations"] = "maybe"
    with pytest.raises(ValidationError):
        RunRequest.model_validate(payload)


def test_contract_field_usage_audit_has_no_unconsumed_decision_fields():
    rows = audit()
    assert all(r["status"] == "CONSUMED" for r in rows)
    assert all(r["decision"] in {"YES", "INFORMATIONAL_ONLY"} for r in rows)


def test_single_worker_is_documented():
    for fn in ("README.md", "HANDOFF_TO_CODEX.md", "CODEX_LAST_MILE_PROMPT.md"):
        text=(ROOT / fn).read_text(encoding="utf-8").lower()
        assert "--workers 1" in text and "single worker" in text
