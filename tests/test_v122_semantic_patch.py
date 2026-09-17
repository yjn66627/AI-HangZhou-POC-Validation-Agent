from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.adapters.yuanqi import YuanqiMappingError, prepare_run_requests
from experiment.decision_engine import make_decision
from experiment.evaluation_contract import compile_live_acceptance
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment
from experiment.pipeline import aggregate_candidate
from experiment.schemas import SchemaValidationError, validate_linked_inputs
from tools.audit_contract_field_usage import audit as contract_usage_audit
from tools.audit_empty_value_semantics import audit as empty_semantics_audit

ROOT = Path(__file__).resolve().parents[1]


def bundle() -> dict:
    return json.loads((ROOT / "examples" / "fx-success_bundle.json").read_text(encoding="utf-8"))


def template() -> dict:
    return json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))


def acceptance(case_id: str, **overrides) -> dict:
    out = {
        "contract_id": f"v122-{case_id}",
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


# 1-6 available_tools 空数组/缺失/null权限语义
def test_available_tools_missing_uses_unrestricted_normalization():
    p = template(); p["enterprise_requirement"].pop("available_tools", None)
    out = prepare_run_requests(p)
    expected = list(dict.fromkeys(x for row in p["candidates"] for x in row.get("tools", [])))
    assert out["task"]["available_tools"] == expected


def test_available_tools_null_uses_unrestricted_normalization():
    p = template(); p["enterprise_requirement"]["available_tools"] = None
    out = prepare_run_requests(p)
    assert set(out["task"]["available_tools"]) == {x for row in p["candidates"] for x in row.get("tools", [])}


def test_available_tools_empty_means_none_allowed():
    p = template(); p["enterprise_requirement"]["available_tools"] = []
    assert prepare_run_requests(p)["task"]["available_tools"] == []


def test_available_tools_allowlist_preserved():
    p = template(); p["enterprise_requirement"]["available_tools"] = ["tool_a"]
    assert prepare_run_requests(p)["task"]["available_tools"] == ["tool_a"]


def test_candidate_tools_are_not_reintroduced_when_available_tools_empty():
    p = template(); p["enterprise_requirement"]["available_tools"] = []
    out = prepare_run_requests(p)
    assert out["candidates"][0]["tools"]
    with pytest.raises(SchemaValidationError, match="candidate_uses_tool_not_available_to_task"):
        validate_linked_inputs(out["task"], out["candidates"][0], out["experiment_specs"][0])


def test_candidate_unapproved_tool_rejected_by_linked_input_gate():
    p = template(); p["enterprise_requirement"]["available_tools"] = ["tool_a"]
    p["candidates"][0]["tools"] = ["tool_b"]
    out = prepare_run_requests(p)
    with pytest.raises(SchemaValidationError, match="candidate_uses_tool_not_available_to_task"):
        validate_linked_inputs(out["task"], out["candidates"][0], out["experiment_specs"][0])


# 7-11 required_tools 不再回退Candidate.tools
@pytest.mark.parametrize("value", ["MISSING", None, []])
def test_required_tools_missing_null_empty_mean_no_explicit_requirement(value):
    p = template()
    if value == "MISSING":
        p["experiment_params"].pop("required_tools", None)
    else:
        p["experiment_params"]["required_tools"] = value
    out = prepare_run_requests(p)
    assert all(x["required_tools"] == [] for x in out["experiment_specs"])


def test_required_tools_nonempty_is_preserved():
    p = template(); p["experiment_params"]["required_tools"] = ["tool_a"]
    out = prepare_run_requests(p)
    assert all(x["required_tools"] == ["tool_a"] for x in out["experiment_specs"])


def test_required_tools_empty_does_not_fallback_to_candidate_tools():
    p = template(); p["experiment_params"]["required_tools"] = []
    p["candidates"][0]["tools"] = ["tool_a"]
    out = prepare_run_requests(p)
    assert out["experiment_specs"][0]["required_tools"] == []


# 12-15 allowed_actions 三态
@pytest.mark.parametrize("mode", ["MISSING", None])
def test_allowed_actions_missing_or_null_uses_default(mode):
    p = acceptance("ACT")
    if mode == "MISSING": p.pop("allowed_actions", None)
    else: p["allowed_actions"] = None
    assert compile_live_acceptance("ACT", p)["allowed_actions"] == ["ANSWER", "CLARIFY", "HANDOFF", "REFUSE"]


def test_allowed_actions_empty_means_none_allowed_and_blocks_pass():
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="no-actions")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], allowed_actions=[]))
    e = evaluate(w, c, b["experiment_spec"], b["task"])
    assert c["allowed_actions"] == []
    assert "no_allowed_action_policy" in e["constraint_violations"]
    assert e["passed"] is False


def test_allowed_actions_whitelist_rejects_other_action():
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="action-whitelist")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], allowed_actions=["HANDOFF"]))
    assert "action_not_accepted_by_contract" in evaluate(w, c, b["experiment_spec"], b["task"])["constraint_violations"]


# 16-22 LIVE decision criteria source 信任边界
@pytest.mark.parametrize("source", ["USER_CONFIRMED", "BUSINESS_CONFIRMED"])
def test_trusted_decision_criteria_sources_compile(source):
    p = acceptance("SRC"); p["decision_criteria"]["source"] = source
    assert compile_live_acceptance("SRC", p)["decision_criteria"]["source"] == source


@pytest.mark.parametrize("source", ["DEMO_DEFAULT", "TEMPLATE_ONLY", "SYSTEM_TEMPLATE"])
def test_template_or_demo_source_cannot_drive_live_decision(source):
    p = acceptance("SRC"); p["decision_criteria"]["source"] = source
    with pytest.raises(ValueError, match="untrusted_decision_criteria_source"):
        compile_live_acceptance("SRC", p)


def test_unknown_decision_criteria_source_rejected():
    p = acceptance("SRC"); p["decision_criteria"]["source"] = "MYSTERY_SOURCE"
    with pytest.raises(ValueError, match="invalid_decision_criteria_source"):
        compile_live_acceptance("SRC", p)


def test_missing_decision_criteria_source_rejected():
    p = acceptance("SRC"); p["decision_criteria"].pop("source")
    with pytest.raises(ValueError, match="decision_criteria_source_required"):
        compile_live_acceptance("SRC", p)


# 23-26 human fallback语义
def _decision_with_fallback(fallback: bool, *, should_escalate: bool) -> tuple[dict, dict]:
    b = bundle(); spec = deepcopy(b["experiment_spec"]); spec["business_constraints"]["human_fallback_available"] = fallback
    w = run_experiment(b["task"], b["candidate"], spec, run_id=f"fallback-{fallback}-{should_escalate}")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], should_escalate=should_escalate))
    e = evaluate(w, c, spec, b["task"])
    return e, make_decision(w, e)


def test_human_review_with_fallback_true_is_human_assisted():
    e, d = _decision_with_fallback(True, should_escalate=True)
    assert e["human_review"]["required"] is True and d["decision"] == "HUMAN_ASSISTED"


def test_human_review_with_fallback_false_defers():
    e, d = _decision_with_fallback(False, should_escalate=True)
    assert "human_fallback_unavailable" in e["constraint_violations"]
    assert d["decision"] == "DEFER"


def test_no_review_required_fallback_false_does_not_fail_by_itself():
    e, d = _decision_with_fallback(False, should_escalate=False)
    assert "human_fallback_unavailable" not in e["constraint_violations"]
    assert d["decision"] == "SUPPORT_CONTROLLED_TRIAL"


def test_comparison_aggregate_does_not_recommend_no_fallback_review_case():
    b = bundle(); spec = deepcopy(b["experiment_spec"]); spec["business_constraints"]["human_fallback_available"] = False
    w = run_experiment(b["task"], b["candidate"], spec, run_id="fallback-agg")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"], should_escalate=True))
    e = evaluate(w, c, spec, b["task"]); d = make_decision(w, e)
    agg = aggregate_candidate(b["candidate"]["candidate_id"], [{"workflow_result": w, "evaluation_result": e, "decision_card": d}], {"allow_human_review": True})
    assert agg["eligible"] is False and d["decision"] != "HUMAN_ASSISTED"


# 27-30 business constraints 支持/不支持分类
def test_known_business_constraint_changes_evaluation():
    b = bundle(); changed = deepcopy(b["task"]); changed["business_constraints"]["max_latency_ms"] = 1
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="known-bc")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"]))
    e = evaluate(w, c, b["experiment_spec"], changed)
    assert e["latency"]["passed"] is False and "latency_above_threshold" in e["constraint_violations"]


def test_unknown_mandatory_business_constraint_blocks_formal_recommendation():
    b = bundle(); changed = deepcopy(b["task"]); changed["business_constraints"]["must_not_use_model_provider"] = "OpenAI"
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="unknown-bc")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"]))
    e = evaluate(w, c, b["experiment_spec"], changed); d = make_decision(w, e)
    assert any(x.startswith("unsupported_mandatory_business_constraint:task:must_not_use_model_provider") for x in e["constraint_violations"])
    assert e["passed"] is False and d["decision"] == "DEFER"


def test_unknown_informational_business_constraint_is_not_a_blocker():
    b = bundle(); changed = deepcopy(b["task"])
    changed["business_constraints"]["future_preference"] = {"value": "prefer-green", "informational_only": True}
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="info-bc")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"]))
    e = evaluate(w, c, b["experiment_spec"], changed)
    assert not any(x.startswith("unsupported_mandatory_business_constraint") for x in e["constraint_violations"])
    assert e["passed"] is True


def test_invalid_human_fallback_boolean_is_rejected():
    b = bundle(); b["experiment_spec"]["business_constraints"]["human_fallback_available"] = "maybe"
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="bad-fallback")
    c = compile_live_acceptance(b["task"]["case_id"], acceptance(b["task"]["case_id"]))
    with pytest.raises(ValueError, match="invalid_boolean"):
        evaluate(w, c, b["experiment_spec"], b["task"])


# 31-33 行为审计 / 空值审计 / 0值保留
def test_contract_field_usage_audit_is_behavioral_and_clean():
    rows = contract_usage_audit()
    assert len(rows) >= 14
    assert all(r["static_status"] == "PASS" and r["behavior_status"] == "PASS" and r["status"] == "CONSUMED" for r in rows)


def test_empty_value_semantics_audit_is_clean():
    rows = empty_semantics_audit()
    assert len(rows) >= 8 and all(r["status"] == "PASS" for r in rows)


def test_zero_cost_threshold_is_not_replaced_by_default():
    p = template(); p["experiment_params"]["success_criteria"]["max_cost"] = 0
    assert prepare_run_requests(p)["experiment_specs"][0]["success_criteria"]["max_cost"] == 0
