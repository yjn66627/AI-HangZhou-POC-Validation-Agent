from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import RUN_STORE, app
from experiment.case_registry import CaseRegistry
from experiment.evaluation_contract import compile_live_acceptance
from experiment.executor_base import ExperimentExecutor
from experiment.experiment_runner import build_fixture_result, run_experiment
from experiment.pipeline import compare_candidates, run_multi_candidate_pipeline
from experiment.schemas import SchemaValidationError, validate_workflow_result

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _bundle() -> dict:
    return json.loads((ROOT / "examples" / "fx-success_bundle.json").read_text(encoding="utf-8"))


def _headers(monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "stage2-key")
    monkeypatch.setenv("EXECUTOR_MODE", "FIXTURE")
    return {"Authorization": "Bearer stage2-key"}


def _poll(url: str, headers: dict[str, str], timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(url, headers=headers)
        assert r.status_code == 200
        data = r.json()
        if data["status"] in {"COMPLETED", "FAILED"}:
            return data
        time.sleep(0.01)
    raise AssertionError("async_run_timeout")


class PatternExecutor(ExperimentExecutor):
    def __init__(self, statuses: list[str]):
        self.statuses = iter(statuses)

    def execute(self, *, task, candidate, experiment_spec, run_id):
        result = build_fixture_result(task, candidate, experiment_spec, run_id)
        result["status"] = next(self.statuses)
        return result


def _run_pattern(statuses: list[str], rules: dict | None = None) -> dict:
    b = deepcopy(_bundle())
    b["experiment_spec"]["repeats"] = len(statuses)
    return run_multi_candidate_pipeline(
        b["task"],
        [b["candidate"]],
        [b["experiment_spec"]],
        registry=CaseRegistry(),
        master_run_id="stage2-repeat",
        executor=PatternExecutor(statuses),
        comparison_rules=rules,
    )


def _trusted_live_result() -> dict:
    b = deepcopy(_bundle())
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="stage2-live")
    w["run_mode"] = "LIVE"
    w["source"].update({
        "kind": "LIVE_CAPTURE",
        "provider": "trusted-live",
        "adapter_id": "trusted-adapter",
        "reference": "remote-stage2",
        "is_fixture": False,
        "is_mock": False,
        "fixture_reason": None,
    })
    for group in ("latency", "cost", "token_usage"):
        for metric in w[group].values():
            if isinstance(metric, dict) and "availability" in metric:
                metric["source"] = "trusted-live"
    w["quality_metrics"]["candidate_reported_score"]["source"] = "trusted-live"
    for call in w["tool_trace"]:
        call["source"] = "trusted-live"
        call["latency_ms"]["source"] = "trusted-live"
    for evidence in w["evidence"]:
        evidence["source"] = "trusted-live"
    w["provenance"].update({
        "producer": "trusted_live_executor",
        "adapter_id": "trusted-adapter",
        "source_endpoint": "https://trusted.example/run",
        "environment": "STAGING",
        "raw_response_ref": "sha256:stage2",
        "raw_response_source": "trusted-live",
        "executor_type": "LIVE_EXECUTOR",
        "remote_execution_id": "remote-stage2",
    })
    w["timestamps"].update({"remote_availability": "AVAILABLE", "received_at": w["timestamps"]["finished_at"]})
    return validate_workflow_result(w)


def test_repeats_three_all_pass_is_eligible():
    result = _run_pattern(["SUCCESS", "SUCCESS", "SUCCESS"])
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["pass_rate"] == 1.0
    assert agg["eligible"] is True


def test_repeats_three_two_pass_default_is_ineligible():
    result = _run_pattern(["SUCCESS", "SUCCESS", "FAILED"])
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["pass_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert agg["eligible"] is False
    assert "pass_rate_below_minimum" in agg["ineligibility_reasons"]


def test_repeats_three_two_pass_can_be_allowed_by_explicit_rules():
    rules = {
        "minimum_pass_rate": 0.66,
        "maximum_failure_rate": 0.34,
        "maximum_timeout_rate": 0.34,
        "minimum_evidence_sufficiency_rate": 0.8,
        "allow_human_review": True,
    }
    result = _run_pattern(["SUCCESS", "SUCCESS", "FAILED"], rules)
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["eligible"] is True
    assert result["comparison_result"]["recommended_candidate_id"] == agg["candidate_id"]


def test_repeats_three_all_fail_is_ineligible():
    result = _run_pattern(["FAILED", "FAILED", "FAILED"])
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["pass_rate"] == 0.0
    assert agg["eligible"] is False


def test_timeout_rate_participates_in_eligibility():
    result = _run_pattern(["SUCCESS", "SUCCESS", "TIMEOUT"], {
        "minimum_pass_rate": 0.66,
        "maximum_failure_rate": 0.34,
        "maximum_timeout_rate": 0.2,
        "minimum_evidence_sufficiency_rate": 0.8,
        "allow_human_review": True,
    })
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["timeout_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert "timeout_rate_above_maximum" in agg["ineligibility_reasons"]


def test_comparison_result_explains_ranking_and_metrics():
    def summary(cid: str, cost: float, latency: float) -> dict:
        return {
            "candidate_id": cid, "repeat_count": 3, "pass_rate": 1.0,
            "quality_mean": 0.9, "quality_std": 0.0, "failure_rate": 0.0,
            "timeout_rate": 0.0, "evidence_sufficiency_rate": 1.0,
            "latency_mean_ms": latency, "latency_p95_ms": latency, "latency_available_rate": 1.0,
            "cost_mean": cost, "cost_total": cost * 3, "cost_currency": "CNY", "cost_available_rate": 1.0,
            "tool_error_count": 0, "safety_block_count": 0, "safety_violation_count": 0,
            "human_review_count": 0, "mandatory_escalation_count": 0, "terminal_failure_count": 0, "execution_plan_violation_count": 0,
            "decision_counts": {"SUPPORT_CONTROLLED_TRIAL": 3}, "eligible": True, "ineligibility_reasons": [],
        }
    result = compare_candidates("C", [{"aggregate": summary("slow-expensive", 0.49, 4900)}, {"aggregate": summary("fast-cheap", 0.01, 300)}])
    assert result["recommended_candidate_id"] == "fast-cheap"
    assert result["eligible_candidates"] == ["slow-expensive", "fast-cheap"]
    assert "cost" in result["ranking_reason"] and "latency" in result["ranking_reason"]
    assert {x["candidate_id"] for x in result["cost_comparison"]} == {"slow-expensive", "fast-cheap"}
    assert {x["candidate_id"] for x in result["latency_comparison"]} == {"slow-expensive", "fast-cheap"}


def test_mandatory_escalation_is_hard_comparison_gate_even_when_human_review_allowed():
    b = deepcopy(_bundle())
    live = {
        "contract_id": "stage2-escalate",
        "allowed_actions": ["ANSWER"],
        "accepted_diagnoses": ["TASK_COMPLETED"],
        "required_tools": b["experiment_spec"]["required_tools"],
        "allowed_tools": b["candidate"]["tools"],
        "forbidden_tools": b["experiment_spec"]["prohibited_tools"],
        "evidence_required": True,
        "decision_criteria": {"source": "BUSINESS_CONFIRMED", "quality": {"status": "REQUIRED", "min_score": 0.8}, "cost": {"status": "REQUIRED", "max_value": 0.5, "currency": "CNY"}, "latency": {"status": "REQUIRED", "max_ms": 5000}},
        "should_escalate": True,
        "guardrail_required": False,
        "root_cause_must_be_evidenced": False,
        "required_response_keywords": [], "required_checks": {}, "forbidden_claims": [],
        "evidence_requirements": {"required_types": [], "required_claim_ids": [], "required_targets": [b["task"]["case_id"]], "require_tool_link": True, "require_action_result": True},
        "notes": "stage2",
    }
    contract = compile_live_acceptance(b["task"]["case_id"], live)
    result = run_multi_candidate_pipeline(
        b["task"], [b["candidate"]], [b["experiment_spec"]], evaluation_contract=contract,
        comparison_rules={"allow_human_review": True}, master_run_id="mandatory-stage2"
    )
    agg = result["candidate_results"][0]["aggregate"]
    assert agg["mandatory_escalation_count"] == 1
    assert agg["eligible"] is False
    assert "mandatory_escalation_present" in agg["ineligibility_reasons"]
    assert result["comparison_result"]["recommended_candidate_id"] is None



def test_correct_guardrail_refusal_remains_eligible_in_comparison():
    b = json.loads((ROOT / "examples" / "fx-risk_bundle.json").read_text(encoding="utf-8"))
    b["experiment_spec"]["simulation"]["profile"] = "SAFE_GUARDRAIL_REFUSAL"
    b["experiment_spec"]["required_tools"] = ["read_permission_scope"]
    contract = compile_live_acceptance("FX-RISK", {
        "contract_id": "safe-guardrail-stage2",
        "allowed_actions": ["REFUSE"],
        "accepted_diagnoses": ["POLICY_REFUSAL"],
        "required_tools": ["read_permission_scope"],
        "allowed_tools": ["read_permission_scope"],
        "forbidden_tools": ["write_resource", "unauthorized_write"],
        "evidence_required": True,
        "decision_criteria": {"source": "BUSINESS_CONFIRMED", "quality": {"status": "REQUIRED", "min_score": 0.7}, "cost": {"status": "REQUIRED", "max_value": 0.05, "currency": "CNY"}, "latency": {"status": "REQUIRED", "max_ms": 3000}},
        "should_escalate": False,
        "guardrail_required": True,
        "root_cause_must_be_evidenced": False,
        "required_response_keywords": [], "required_checks": {}, "forbidden_claims": [],
        "evidence_requirements": {"required_types": [], "required_claim_ids": [], "required_targets": ["FX-RISK"], "require_tool_link": True, "require_action_result": True},
        "notes": "stage2 safety semantic",
    })
    result = run_multi_candidate_pipeline(
        b["task"], [b["candidate"]], [b["experiment_spec"]], evaluation_contract=contract, master_run_id="safe-guardrail-comparison"
    )
    repeat = result["candidate_results"][0]["repeats"][0]
    assert repeat["evaluation_result"]["safety"]["correct_refusal"] is True
    assert repeat["evaluation_result"]["safety"]["violation"] is False
    assert repeat["decision_card"]["decision"] == "SUPPORT_CONTROLLED_TRIAL"
    assert result["candidate_results"][0]["aggregate"]["eligible"] is True
    assert result["comparison_result"]["recommended_candidate_id"] == b["candidate"]["candidate_id"]

def test_live_tool_trace_source_conflict_is_rejected():
    w = _trusted_live_result()
    w["tool_trace"][0]["source"] = "FIXTURE"
    with pytest.raises(SchemaValidationError, match="live_tool_trace_source"):
        validate_workflow_result(w)


def test_live_evidence_source_conflict_is_rejected():
    w = _trusted_live_result()
    w["evidence"][0]["source"] = "MOCK"
    with pytest.raises(SchemaValidationError, match="live_evidence_source"):
        validate_workflow_result(w)


def test_live_raw_response_source_conflict_is_rejected():
    w = _trusted_live_result()
    w["provenance"]["raw_response_source"] = "SANDBOX"
    with pytest.raises(SchemaValidationError, match="live_raw_response_source"):
        validate_workflow_result(w)


def test_live_provenance_producer_conflict_is_rejected():
    w = _trusted_live_result()
    w["provenance"]["producer"] = "fixture-runner"
    with pytest.raises(SchemaValidationError, match="fixture_mock_or_sandbox_producer"):
        validate_workflow_result(w)



def test_live_missing_remote_and_raw_reference_is_rejected():
    w = _trusted_live_result()
    w["provenance"]["remote_execution_id"] = None
    w["provenance"]["raw_response_ref"] = None
    w["provenance"]["raw_response_source"] = None
    w["source"]["reference"] = "live-without-grounded-remote-ref"
    with pytest.raises(SchemaValidationError, match="live_requires_remote_execution_or_raw_response_reference"):
        validate_workflow_result(w)

def test_yuanqi_api_missing_required_section_rejected(monkeypatch):
    headers = _headers(monkeypatch)
    payload = json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    payload.pop("experiment_params")
    r = client.post("/api/v1/yuanqi/runs", json=payload, headers=headers)
    assert r.status_code == 422


def test_yuanqi_api_wrong_type_rejected(monkeypatch):
    headers = _headers(monkeypatch)
    payload = json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    payload["candidates"] = {"candidate_id": "not-a-list"}
    r = client.post("/api/v1/yuanqi/runs", json=payload, headers=headers)
    assert r.status_code == 422


def test_yuanqi_multi_candidate_payload_enters_api(monkeypatch):
    headers = _headers(monkeypatch)
    RUN_STORE.clear()
    payload = json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    payload["candidates"].append({**payload["candidates"][0], "candidate_id": "cand-2", "name": "候选2"})
    payload["experiment_params"]["execution_mode"] = "FIXTURE"
    payload["experiment_params"]["simulation_profiles_by_candidate"] = {"cand-1": "NORMAL_SUCCESS", "cand-2": "QUALITY_LOW"}
    r = client.post("/api/v1/yuanqi/runs", json=payload, headers=headers)
    assert r.status_code == 202
    done = _poll(r.json()["result_url"], headers)
    assert done["status"] == "COMPLETED"
    assert len(done["candidate_results"]) == 2
    assert done["comparison_result"]["case_id"] == "LIVE-DEMO"
