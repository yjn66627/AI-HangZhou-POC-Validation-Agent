import json
from copy import deepcopy
from pathlib import Path

from experiment.decision_engine import make_decision
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment

ROOT = Path(__file__).resolve().parents[1]


def eval_case(name):
    b = json.loads((ROOT / "examples" / f"{name}_bundle.json").read_text(encoding="utf-8"))
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id=f"run-{name}")
    return b, w, evaluate(w, b["case_spec"], b["experiment_spec"])


def test_success_passes_independent_rules():
    _, _, e = eval_case("fx-success")
    assert e["passed"] is True
    assert e["quality"]["source"] == "INDEPENDENT_RULES"
    assert e["evidence"]["status"] == "SUFFICIENT"


def test_quality_low_does_not_trust_candidate_self_report():
    _, w, e = eval_case("fx-quality")
    assert w["quality_metrics"]["candidate_reported_score"]["value"] == 0.95
    assert e["quality"]["score"] < 0.8
    assert e["quality"]["passed"] is False
    assert "candidate_reported_quality_diverges_from_independent_evaluation" in e["constraint_violations"]


def test_timeout_is_handled_but_never_passes():
    _, _, e = eval_case("fx-timeout")
    assert e["run_status"] == "TIMEOUT"
    assert e["passed"] is False
    assert e["error_handling"] == "HANDLED"
    assert "run_status_not_success:TIMEOUT" in e["constraint_violations"]


def test_missing_evidence_is_explicit():
    _, _, e = eval_case("fx-evidence")
    assert e["evidence"]["status"] == "INSUFFICIENT"
    assert "evidence_not_sufficient" in e["constraint_violations"]


def test_high_risk_attempt_is_severe():
    _, w, e = eval_case("fx-risk")
    assert w["output"]["guardrail_blocked"] is True
    assert e["severe_error"] is True
    assert any(x.startswith("unauthorized_attempt") for x in e["severe_error_reasons"])


def test_partial_status_cannot_pass(success_bundle):
    b=deepcopy(success_bundle); b["experiment_spec"]["simulation"]["profile"]="PARTIAL_OUTPUT"
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="partial")
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    d=make_decision(w,e)
    assert e["passed"] is False
    assert "run_status_not_success:PARTIAL" in e["constraint_violations"]
    assert d["decision"] != "SUPPORT_CONTROLLED_TRIAL"


def test_failed_status_cannot_pass(success_bundle):
    b=deepcopy(success_bundle)
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="failed")
    w["status"]="FAILED"
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    assert e["passed"] is False
    assert "run_status_not_success:FAILED" in e["constraint_violations"]


def test_currency_mismatch_is_not_comparable(success_bundle):
    b=deepcopy(success_bundle)
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="currency")
    w["cost"]["currency"]="USD"
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    assert e["cost"]["comparable"] is False
    assert e["cost"]["passed"] is False
    assert "cost_currency_mismatch" in e["constraint_violations"]


def test_not_provided_cost_and_latency_block_pass(success_bundle):
    b=deepcopy(success_bundle); b["experiment_spec"]["simulation"]["profile"]="METRICS_MISSING"
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="missing-metrics")
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    d=make_decision(w,e)
    assert e["passed"] is False
    assert "cost_metric_unavailable" in e["constraint_violations"]
    assert "latency_metric_unavailable" in e["constraint_violations"]
    assert d["decision"] == "INSUFFICIENT_EVIDENCE"


def test_irrelevant_evidence_is_insufficient(success_bundle):
    b=deepcopy(success_bundle)
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="irrelevant")
    w["evidence"][0]["claim"]="今天天气很好。"
    w["evidence"][0]["content"]="可用 sunny"
    w["evidence"][0]["claim_ids"]=["weather_availability"]
    w["evidence"][0]["target"]="WEATHER"
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    assert e["evidence"]["status"] == "INSUFFICIENT"
    assert any("target_not_linked_to_case" in x for x in e["evidence"]["reasons"])


def test_contradicting_evidence_is_conflicting(success_bundle):
    b=deepcopy(success_bundle)
    w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="conflict")
    w["evidence"].append({"evidence_id":"ev-contradict","evidence_type":"DOCUMENT","claim":"结果不支持当前结论","source_ref":"doc:test","support_level":"CONTRADICTS","content":"contradiction","claim_ids":["contradiction"],"target":"FX-SUCCESS","action":"read","result":"contradiction"})
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    assert e["evidence"]["status"] == "CONFLICTING"
