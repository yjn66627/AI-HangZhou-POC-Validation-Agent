from __future__ import annotations

from copy import deepcopy

import pytest

from experiment.decision_engine import make_decision
from experiment.evaluator import evaluate
from experiment.executor_base import ExperimentExecutor
from experiment.experiment_runner import build_fixture_result, run_experiment
from experiment.pipeline import run_multi_candidate_pipeline
from experiment.schemas import validate_workflow_result


def _eval(bundle: dict, workflow: dict | None = None) -> dict:
    b = deepcopy(bundle)
    w = workflow or run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="v123-eval")
    return evaluate(w, b["case_spec"], b["experiment_spec"], b["task"], b["candidate"])


def _replace_first_tool(workflow: dict, tool: str) -> dict:
    w = deepcopy(workflow)
    assert w["tool_trace"]
    w["tool_trace"][0]["tool"] = tool
    call_id = w["tool_trace"][0]["tool_call_id"]
    for ev in w["evidence"]:
        if ev["evidence_id"] in w["tool_trace"][0]["evidence_refs"]:
            ev["source_ref"] = call_id
    return validate_workflow_result(w)


def _trusted_live(workflow: dict) -> dict:
    w = deepcopy(workflow)
    w["run_mode"] = "LIVE"
    w["source"].update({
        "kind": "LIVE_CAPTURE", "provider": "trusted-live", "adapter_id": "trusted-adapter",
        "reference": "remote-v123", "is_fixture": False, "is_mock": False, "fixture_reason": None,
    })
    for group in ("latency", "cost", "token_usage"):
        for value in w[group].values():
            if isinstance(value, dict) and "availability" in value:
                value["source"] = "trusted-live"
    w["quality_metrics"]["candidate_reported_score"]["source"] = "trusted-live"
    for call in w["tool_trace"]:
        call["source"] = "trusted-live"
        call["latency_ms"]["source"] = "trusted-live"
    for ev in w["evidence"]:
        ev["source"] = "trusted-live"
    w["provenance"].update({
        "producer": "trusted_live_executor", "adapter_id": "trusted-adapter",
        "source_endpoint": "https://trusted.example/run", "environment": "STAGING",
        "raw_response_ref": "sha256:v123", "raw_response_source": "trusted-live",
        "executor_type": "LIVE_EXECUTOR", "remote_execution_id": "remote-v123",
    })
    w["timestamps"]["remote_availability"] = "AVAILABLE"
    return validate_workflow_result(w)


def _no_tool_bundle(success_bundle: dict, *, require_evidence: bool = False) -> dict:
    b = deepcopy(success_bundle)
    b["task"]["available_tools"] = []
    b["candidate"]["tools"] = []
    b["experiment_spec"]["required_tools"] = []
    b["experiment_spec"]["success_criteria"]["require_tool_trace"] = False
    b["experiment_spec"]["success_criteria"]["require_evidence"] = require_evidence
    b["case_spec"]["expected"]["required_tools"] = []
    b["case_spec"]["expected"]["allowed_tools"] = []
    b["case_spec"]["expected"]["evidence_required"] = require_evidence
    return b


def test_task_allowlist_rejects_shadow_tool(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="task-shadow")
    w = _replace_first_tool(w, "shadow_tool")
    e = _eval(b, w)
    assert e["passed"] is False
    assert "shadow_tool" in e["execution_plan_integrity"]["unexpected_tools"]
    assert any(x == "unexpected_runtime_tool_task:shadow_tool" for x in e["constraint_violations"])


def test_candidate_declaration_rejects_other_task_allowed_tool(success_bundle):
    b = deepcopy(success_bundle)
    b["task"]["available_tools"] = ["retrieve_context", "search_docs"]
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="candidate-shadow")
    w = _replace_first_tool(w, "search_docs")
    e = _eval(b, w)
    assert e["passed"] is False
    assert "unexpected_runtime_tool_candidate:search_docs" in e["constraint_violations"]
    assert "unexpected_runtime_tool_task:search_docs" not in e["constraint_violations"]


def test_task_multi_candidate_single_declared_tool_still_rejects_other(success_bundle):
    b = deepcopy(success_bundle)
    b["task"]["available_tools"] = ["retrieve_context", "search_docs", "tool_x"]
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="candidate-one")
    w = _replace_first_tool(w, "tool_x")
    e = _eval(b, w)
    assert e["execution_plan_integrity"]["status"] == "FAIL"
    assert e["execution_plan_integrity"]["declared_tools"] == ["retrieve_context"]


def test_task_none_allowed_any_runtime_tool_fails(success_bundle):
    b = _no_tool_bundle(success_bundle)
    clean = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="none-clean")
    donor = run_experiment(success_bundle["task"], success_bundle["candidate"], success_bundle["experiment_spec"], run_id="donor")
    w = deepcopy(clean)
    w["tool_trace"] = deepcopy(donor["tool_trace"])
    w["evidence"] = deepcopy(donor["evidence"])
    e = _eval(b, validate_workflow_result(w))
    assert e["passed"] is False
    assert "unexpected_runtime_tool_task:retrieve_context" in e["constraint_violations"]


def test_candidate_empty_any_candidate_tool_call_fails(success_bundle):
    b = deepcopy(success_bundle)
    b["candidate"]["tools"] = []
    b["experiment_spec"]["required_tools"] = []
    b["case_spec"]["expected"]["required_tools"] = []
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="cand-empty")
    donor = run_experiment(success_bundle["task"], success_bundle["candidate"], success_bundle["experiment_spec"], run_id="donor2")
    w["tool_trace"] = deepcopy(donor["tool_trace"]); w["evidence"] = deepcopy(donor["evidence"])
    e = _eval(b, validate_workflow_result(w))
    assert "unexpected_runtime_tool_candidate:retrieve_context" in e["constraint_violations"]


def test_required_tool_missing_fails(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="missing-required")
    w["tool_trace"] = []; w["evidence"] = []
    e = _eval(b, validate_workflow_result(w))
    assert e["execution_plan_integrity"]["missing_required_tools"] == ["retrieve_context"]
    assert "missing_required_tool:retrieve_context" in e["constraint_violations"]
    assert e["passed"] is False


def test_required_empty_candidate_empty_runner_does_not_create_default_tool(success_bundle):
    b = _no_tool_bundle(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="no-default")
    assert w["tool_trace"] == []
    assert w["evidence"] == []
    assert w["latency"]["tool_ms"]["value"] == 0.0


def test_task_candidate_required_all_empty_has_empty_trace(success_bundle):
    b = _no_tool_bundle(success_bundle)
    w = build_fixture_result(b["task"], b["candidate"], b["experiment_spec"], "all-empty")
    assert w["tool_trace"] == []


def test_no_tools_but_evidence_required_fails_without_fabrication(success_bundle):
    b = _no_tool_bundle(success_bundle, require_evidence=True)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="evidence-no-tool")
    e = _eval(b, w)
    assert w["tool_trace"] == [] and w["evidence"] == []
    assert e["evidence"]["status"] == "INSUFFICIENT"
    assert e["passed"] is False


def test_execution_violation_is_structured_in_evaluation(success_bundle):
    b = deepcopy(success_bundle)
    w = _replace_first_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="structured"), "shadow_tool")
    e = _eval(b, w)
    x = e["execution_plan_integrity"]
    assert x["status"] == "FAIL"
    assert x["actual_tools"] == ["shadow_tool"]
    assert x["required_tools"] == ["retrieve_context"]
    assert x["violations"]


def test_execution_violation_decision_is_not_recommended(success_bundle):
    b = deepcopy(success_bundle)
    w = _replace_first_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="decision"), "shadow_tool")
    e = _eval(b, w); d = make_decision(w, e)
    assert d["decision"] == "DEFER"
    assert "执行计划" in d["headline"]


class UnauthorizedExecutor(ExperimentExecutor):
    def __init__(self, bad_repeat: int | None = None):
        self.i = 0; self.bad_repeat = bad_repeat
    def execute(self, *, task, candidate, experiment_spec, run_id):
        self.i += 1
        w = build_fixture_result(task, candidate, experiment_spec, run_id)
        if self.bad_repeat is None or self.i == self.bad_repeat:
            w = _replace_first_tool(w, "shadow_tool")
        return w


def test_execution_violation_candidate_not_recommended_by_comparison(success_bundle):
    b = deepcopy(success_bundle)
    b["task"]["available_tools"] = ["retrieve_context", "shadow_tool"]
    result = run_multi_candidate_pipeline(
        b["task"], [b["candidate"]], [b["experiment_spec"]],
        registry=__import__("experiment.case_registry", fromlist=["CaseRegistry"]).CaseRegistry(),
        master_run_id="cmp-integrity", executor=UnauthorizedExecutor(),
        comparison_rules={"minimum_pass_rate": 0.0, "maximum_failure_rate": 1.0, "maximum_timeout_rate": 1.0, "minimum_evidence_sufficiency_rate": 0.0, "allow_human_review": True},
    )
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["execution_plan_violation_count"] == 1
    assert agg["eligible"] is False
    assert result["comparison_result"]["recommended_candidate_id"] is None


def test_legal_execution_plan_passes(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="legal")
    e = _eval(b, w)
    assert e["execution_plan_integrity"]["status"] == "PASS"
    assert e["execution_plan_integrity"]["actual_tools"] == ["retrieve_context"]


def test_live_source_can_be_trusted_but_unauthorized_tool_still_fails(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="live-integrity")
    w = _replace_first_tool(w, "shadow_tool")
    w = _trusted_live(w)
    e = _eval(b, w)
    assert w["run_mode"] == "LIVE"
    assert e["execution_plan_integrity"]["status"] == "FAIL"
    assert e["passed"] is False


def test_fixture_source_valid_but_undeclared_tool_still_fails(success_bundle):
    b = deepcopy(success_bundle)
    w = _replace_first_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="fixture-integrity"), "shadow_tool")
    e = _eval(b, w)
    assert w["run_mode"] == "FIXTURE"
    assert e["execution_plan_integrity"]["status"] == "FAIL"


def test_one_unauthorized_repeat_is_hard_comparison_gate(success_bundle):
    b = deepcopy(success_bundle)
    b["task"]["available_tools"] = ["retrieve_context", "shadow_tool"]
    b["experiment_spec"]["repeats"] = 3
    rules = {"minimum_pass_rate": 0.5, "maximum_failure_rate": 1.0, "maximum_timeout_rate": 1.0, "minimum_evidence_sufficiency_rate": 0.0, "allow_human_review": True}
    result = run_multi_candidate_pipeline(
        b["task"], [b["candidate"]], [b["experiment_spec"]],
        registry=__import__("experiment.case_registry", fromlist=["CaseRegistry"]).CaseRegistry(),
        master_run_id="repeat-integrity", executor=UnauthorizedExecutor(bad_repeat=2), comparison_rules=rules,
    )
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["pass_rate"] == pytest.approx(2/3, abs=1e-6)
    assert agg["execution_plan_violation_count"] == 1
    assert "execution_plan_violation_present" in agg["ineligibility_reasons"]
    assert agg["eligible"] is False


def test_prohibited_runtime_tool_is_execution_plan_violation(success_bundle):
    b = deepcopy(success_bundle)
    b["task"]["available_tools"].append("write_resource")
    b["candidate"]["tools"].append("write_resource")
    w = _replace_first_tool(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="forbidden"), "write_resource")
    e = _eval(b, w)
    assert "write_resource" in e["execution_plan_integrity"]["forbidden_tools"]
    assert "forbidden_runtime_tool:write_resource" in e["constraint_violations"]
