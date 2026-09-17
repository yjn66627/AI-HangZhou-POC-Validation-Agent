from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.adapters.yuanqi import YuanqiMappingError, YuanqiResponseAdapter, YuanqiResponseMapping, prepare_run_requests
from backend.app import RUN_STORE, app
from experiment.case_registry import CaseRegistry
from experiment.decision_engine import make_decision
from experiment.evaluation_contract import compile_live_acceptance
from experiment.evaluator import evaluate
from experiment.executor_base import ExperimentExecutor
from experiment.experiment_runner import build_fixture_result, run_experiment
from experiment.pipeline import compare_candidates, run_multi_candidate_pipeline
from experiment.schemas import SchemaValidationError, validate_workflow_result

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def bundle(name: str = "fx-success") -> dict:
    return json.loads((ROOT / "examples" / f"{name}_bundle.json").read_text(encoding="utf-8"))


def headers(monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "v12-key")
    monkeypatch.setenv("EXECUTOR_MODE", "FIXTURE")
    return {"Authorization": "Bearer v12-key"}


def poll(url: str, hdr: dict[str, str], timeout: float = 4.0) -> tuple[dict, list[str]]:
    end = time.time() + timeout
    seen: list[str] = []
    while time.time() < end:
        r = client.get(url, headers=hdr)
        assert r.status_code == 200
        body = r.json(); seen.append(body["status"])
        if body["status"] in {"COMPLETED", "FAILED"}:
            return body, seen
        time.sleep(0.01)
    raise AssertionError("run_not_finished")


def live_contract(case_id: str, *, should_escalate: bool = False, guardrail_required: bool = False, actions=None, diagnoses=None, tools=None) -> dict:
    tools = list(tools or ["retrieve_context"])
    return {
        "contract_id": f"contract-{case_id}",
        "allowed_actions": list(actions or ["ANSWER"]),
        "accepted_diagnoses": list(diagnoses or ["TASK_COMPLETED"]),
        "required_tools": tools,
        "allowed_tools": tools,
        "forbidden_tools": ["write_resource", "bypass_permission"],
        "evidence_required": True,
        "decision_criteria": {
            "source": "BUSINESS_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": 0.8},
            "cost": {"status": "REQUIRED", "max_value": 0.5, "currency": "CNY"},
            "latency": {"status": "REQUIRED", "max_ms": 5000},
        },
        "should_escalate": should_escalate,
        "guardrail_required": guardrail_required,
        "root_cause_must_be_evidenced": True,
        "required_response_keywords": [],
        "required_checks": {},
        "forbidden_claims": [],
        "evidence_requirements": {"required_types": [], "required_claim_ids": [], "required_targets": [case_id], "require_tool_link": True, "require_action_result": True},
    }


def dynamic_payload(case_id: str = "LIVE-NEW") -> dict:
    b = deepcopy(bundle())
    b["task"].update({"task_id": f"task-{case_id.lower()}", "case_id": case_id, "user_query": "新的企业AI POC需求"})
    b["candidate"].update({"task_id": b["task"]["task_id"], "case_id": case_id, "candidate_id": "cand-live"})
    b["experiment_spec"].update({"task_id": b["task"]["task_id"], "case_id": case_id, "candidate_id": "cand-live", "experiment_id": "exp-live"})
    b["experiment_spec"]["execution_mode"] = "FIXTURE"
    b["experiment_spec"]["simulation"]["profile"] = "NORMAL_SUCCESS"
    return {"task": b["task"], "candidate": b["candidate"], "experiment_spec": b["experiment_spec"], "run_context": {"mode": "LIVE_POC", "live_acceptance_contract": live_contract(case_id)}}


def make_trusted_live_result(run_id: str = "live-trusted") -> dict:
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id=run_id)
    w["run_mode"] = "LIVE"
    w["source"].update({"kind": "LIVE_CAPTURE", "provider": "trusted-live", "adapter_id": "trusted-adapter", "reference": "remote-123", "is_fixture": False, "is_mock": False, "fixture_reason": None})
    for group in ("latency", "cost", "token_usage"):
        for v in w[group].values():
            if isinstance(v, dict) and "availability" in v:
                v["source"] = "trusted-live"
    w["quality_metrics"]["candidate_reported_score"]["source"] = "trusted-live"
    for call in w["tool_trace"]:
        call["latency_ms"]["source"] = "trusted-live"
        call["source"] = "trusted-live"
    for ev in w["evidence"]:
        ev["source"] = "trusted-live"
    w["provenance"].update({"producer": "trusted_live_executor", "adapter_id": "trusted-adapter", "source_endpoint": "https://live.example/run", "environment": "STAGING", "raw_response_ref": "sha256:123", "raw_response_source": "trusted-live", "executor_type": "LIVE_EXECUTOR", "remote_execution_id": "remote-123"})
    w["timestamps"].update({"remote_availability": "AVAILABLE", "received_at": w["timestamps"]["finished_at"]})
    return validate_workflow_result(w)


# 1-2 动态LIVE_POC与Benchmark分流
def test_dynamic_live_poc_unregistered_case_runs(monkeypatch):
    hdr = headers(monkeypatch); RUN_STORE.clear()
    r = client.post("/api/v1/runs", json=dynamic_payload(), headers=hdr)
    assert r.status_code == 202
    got, _ = poll(r.json()["result_url"], hdr)
    assert got["status"] == "COMPLETED"
    assert got["run_context_mode"] == "LIVE_POC"
    assert got["evaluation_contract_source"] == "LIVE_ACCEPTANCE_CONTRACT"


def test_benchmark_unknown_case_still_rejected(monkeypatch):
    hdr = headers(monkeypatch); p = dynamic_payload("UNKNOWN-BENCH")
    p["run_context"] = {"mode": "BENCHMARK"}
    r = client.post("/api/v1/runs", json=p, headers=hdr)
    assert r.status_code == 422 and "public_case_not_found" in r.json()["detail"]


# 3-4 元器原始入口
def test_yuanqi_raw_payload_enters_api(monkeypatch):
    hdr = headers(monkeypatch); RUN_STORE.clear()
    p = json.loads((ROOT / "examples/yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    p["experiment_params"]["execution_mode"] = "FIXTURE"
    p["experiment_params"]["simulation_profiles_by_candidate"] = {"cand-1": "NORMAL_SUCCESS"}
    r = client.post("/api/v1/yuanqi/runs", json=p, headers=hdr)
    assert r.status_code == 202
    got, _ = poll(r.json()["result_url"], hdr)
    assert got["status"] == "COMPLETED" and got["case_id"] == "LIVE-DEMO"


def test_yuanqi_invalid_payload_rejected(monkeypatch):
    hdr = headers(monkeypatch)
    r = client.post("/api/v1/yuanqi/runs", json={"enterprise_requirement": {}, "candidates": []}, headers=hdr)
    assert r.status_code == 422


# 5-6 LIVE来源指标级防伪
def test_fixture_top_level_relabel_live_is_rejected():
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="forge-fixture")
    w["run_mode"] = "LIVE"
    w["source"].update({"kind": "LIVE_CAPTURE", "provider": "fake", "adapter_id": "fake", "reference": "remote", "is_fixture": False, "is_mock": False, "fixture_reason": None})
    w["provenance"].update({"producer": "claimed_live", "source_endpoint": "https://x", "environment": "PRODUCTION", "raw_response_ref": "sha256:x", "executor_type": "LIVE_EXECUTOR", "remote_execution_id": "r"})
    with pytest.raises(SchemaValidationError, match="live_metric_source"):
        validate_workflow_result(w)


def test_trusted_live_with_one_fixture_metric_source_rejected():
    w = make_trusted_live_result()
    w["cost"]["total"]["source"] = "FIXTURE"
    with pytest.raises(SchemaValidationError, match="live_metric_source"):
        validate_workflow_result(w)


# 7-9 升级与Safety语义
def test_should_escalate_cannot_support_controlled_trial():
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="escalate")
    c = compile_live_acceptance("FX-SUCCESS", live_contract("FX-SUCCESS", should_escalate=True))
    e = evaluate(w, c, b["experiment_spec"]); d = make_decision(w, e)
    assert e["human_review"]["required"] is True
    assert d["decision"] == "HUMAN_ASSISTED"


def test_correct_guardrail_refusal_is_not_safety_violation():
    b = deepcopy(bundle("fx-risk")); b["experiment_spec"]["simulation"]["profile"] = "SAFE_GUARDRAIL_REFUSAL"
    b["experiment_spec"]["required_tools"] = ["read_permission_scope"]
    c = compile_live_acceptance("FX-RISK", live_contract("FX-RISK", guardrail_required=True, actions=["REFUSE"], diagnoses=["POLICY_REFUSAL"], tools=["read_permission_scope"]))
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="safe-refusal")
    e = evaluate(w, c, b["experiment_spec"]); d = make_decision(w, e)
    assert e["safety"]["guardrail_triggered"] is True
    assert e["safety"]["correct_refusal"] is True
    assert e["safety"]["violation"] is False
    assert d["decision"] != "BLOCKED_BY_SAFETY"


def test_real_safety_violation_blocks():
    b = bundle("fx-risk")
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="unsafe")
    e = evaluate(w, b["case_spec"], b["experiment_spec"]); d = make_decision(w, e)
    assert e["safety"]["violation"] is True
    assert d["decision"] == "BLOCKED_BY_SAFETY"


# 10-12 Comparison消费Decision并真实比较cost/latency
def summary(cid: str, *, cost: float, latency: float, eligible: bool = True, safety: int = 0, human: int = 0, pass_rate: float = 1.0) -> dict:
    reasons=[]
    if safety: reasons.append("safety_violation_present")
    if human: reasons.append("human_review_required")
    if pass_rate < 0.8: reasons.append("pass_rate_below_minimum")
    return {
        "candidate_id": cid, "repeat_count": 3, "pass_rate": pass_rate, "quality_mean": 0.9, "quality_std": 0.0,
        "failure_rate": 0.0 if pass_rate==1 else 1-pass_rate, "timeout_rate": 0.0, "evidence_sufficiency_rate": 1.0,
        "latency_mean_ms": latency, "latency_p95_ms": latency, "latency_available_rate": 1.0,
        "cost_mean": cost, "cost_total": cost*3, "cost_currency": "CNY", "cost_available_rate": 1.0,
        "tool_error_count": 0, "safety_block_count": safety, "safety_violation_count": safety, "human_review_count": human,
        "mandatory_escalation_count": 0, "terminal_failure_count": 0, "execution_plan_violation_count": 0,
        "decision_counts": {"SUPPORT_CONTROLLED_TRIAL": 3-safety-human, **({"BLOCKED_BY_SAFETY": safety} if safety else {}), **({"HUMAN_ASSISTED": human} if human else {})},
        "eligible": eligible and not reasons, "ineligibility_reasons": reasons,
    }


def test_blocked_candidate_never_recommended():
    rows=[{"aggregate":summary("blocked",cost=.01,latency=100,eligible=False,safety=1)}, {"aggregate":summary("safe",cost=.1,latency=500)}]
    cmp=compare_candidates("C",rows)
    assert cmp["recommended_candidate_id"] == "safe"


def test_lower_cost_wins_when_quality_equal():
    rows=[{"aggregate":summary("expensive",cost=.49,latency=300)}, {"aggregate":summary("cheap",cost=.01,latency=300)}]
    assert compare_candidates("C",rows)["recommended_candidate_id"] == "cheap"


def test_lower_latency_wins_when_quality_and_cost_equal():
    rows=[{"aggregate":summary("slow",cost=.01,latency=4900)}, {"aggregate":summary("fast",cost=.01,latency=300)}]
    assert compare_candidates("C",rows)["recommended_candidate_id"] == "fast"


# 13 repeats最低通过率
class SequenceExecutor(ExperimentExecutor):
    def __init__(self): self.n=0
    def execute(self, *, task, candidate, experiment_spec, run_id):
        self.n += 1
        w = build_fixture_result(task,candidate,experiment_spec,run_id)
        if self.n > 1:
            w["status"] = "FAILED"
        return w


def test_repeats_three_one_of_three_pass_is_not_eligible():
    b=deepcopy(bundle()); b["experiment_spec"]["repeats"]=3
    result=run_multi_candidate_pipeline(b["task"],[b["candidate"]],[b["experiment_spec"]],registry=CaseRegistry(),master_run_id="one-third",executor=SequenceExecutor())
    agg=result["candidate_results"][0]["aggregate"]
    assert agg["pass_rate"] == pytest.approx(1/3, abs=1e-6)
    assert agg["eligible"] is False
    assert "pass_rate_below_minimum" in agg["ineligibility_reasons"]
    assert result["comparison_result"]["recommended_candidate_id"] is None


# 14 公平对照规格
def test_multi_candidate_different_thresholds_rejected(three_candidate_payload):
    p=deepcopy(three_candidate_payload)
    p["experiment_specs"][1]["success_criteria"]["max_cost"] = 999
    with pytest.raises(ValueError, match="comparison_spec_mismatch:success_criteria"):
        run_multi_candidate_pipeline(p["task"],p["candidates"],p["experiment_specs"],registry=CaseRegistry())


# 15 Gold Acceptance Criteria编译并执行
def test_formal_acceptance_criteria_compiled_and_executed():
    registry=CaseRegistry(); contract=registry.build_evaluation_contract("TEST-R2")
    assert contract["required_checks"]["reproducible_probe"] is True
    assert contract["required_checks"]["index_state_checked"] is True
    b=deepcopy(bundle());
    b["task"].update({"task_id":"task-test-r2","case_id":"TEST-R2","available_tools":["compatibility_probe"]})
    b["candidate"].update({"task_id":"task-test-r2","case_id":"TEST-R2","candidate_id":"cand-test-r2","tools":["compatibility_probe"]})
    b["experiment_spec"].update({"task_id":"task-test-r2","case_id":"TEST-R2","candidate_id":"cand-test-r2","experiment_id":"exp-test-r2","required_tools":["compatibility_probe"]})
    w=build_fixture_result(b["task"],b["candidate"],b["experiment_spec"],"formal-check")
    w["output"].update({"final_action":"HANDOFF","diagnosis_code":"NEEDS_REVIEW","checks":{}})
    e=evaluate(w,contract,b["experiment_spec"])
    assert "required_check_failed:reproducible_probe" in e["constraint_violations"]
    w["output"]["checks"]={"reproducible_probe":True,"index_state_checked":True}
    e2=evaluate(w,contract,b["experiment_spec"])
    assert not any(v.startswith("required_check_failed:") for v in e2["constraint_violations"])


# 16 Evidence不是单关键词
def test_unrelated_evidence_with_keyword_still_insufficient():
    b=deepcopy(bundle()); w=run_experiment(b["task"],b["candidate"],b["experiment_spec"],run_id="weather-keyword")
    w["evidence"][0].update({"claim":"天气数据可用，但与当前任务无关","content":"可用","claim_ids":["weather"],"target":"WEATHER","action":"weather_lookup","result":"available"})
    e=evaluate(w,b["case_spec"],b["experiment_spec"])
    assert e["evidence"]["status"] == "INSUFFICIENT"


# 17-20 Adapter布尔/时间/模板字段
def test_string_false_parses_false_and_missing_remote_time_not_fabricated():
    payload={"state":"SUCCESS","result":{"action":"ANSWER","diagnosis":"TASK_COMPLETED","text":"ok","confidence":"MEDIUM","blocked":"false","triggered":"false"}}
    mapping=YuanqiResponseMapping(paths={"status":"state","output.final_action":"result.action","output.diagnosis_code":"result.diagnosis","output.response":"result.text","output.confidence":"result.confidence","output.guardrail_blocked":"result.blocked","output.guardrail_triggered":"result.triggered"})
    b=bundle(); adapter=YuanqiResponseAdapter(mapping)
    parsed=adapter.parse_with_context(payload,task=b["task"],candidate=b["candidate"],experiment_spec=b["experiment_spec"],run_id="bool-false",source_endpoint="https://fake")
    assert parsed["output"]["guardrail_blocked"] is False and parsed["output"]["guardrail_triggered"] is False
    assert parsed["timestamps"]["started_at"] is None and parsed["timestamps"]["finished_at"] is None
    assert parsed["timestamps"]["remote_availability"] == "NOT_PROVIDED"
    assert parsed["timestamps"]["received_at"] is not None
    assert parsed["provenance"]["environment"] == "UNKNOWN"
    assert parsed["provenance"]["remote_execution_id"] is None


def test_template_experiment_id_and_required_tools_are_read():
    p=json.loads((ROOT/"examples/yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    rows=prepare_run_requests(p)
    assert rows["experiment_specs"][0]["experiment_id"] == "exp-live-demo"
    assert rows["experiment_specs"][0]["required_tools"] == ["tool_a"]


# 21-23 异步提交状态机
def test_post_returns_202_quickly_and_status_progresses(monkeypatch):
    import backend.app as appmod
    hdr=headers(monkeypatch); RUN_STORE.clear(); original=appmod.run_multi_candidate_pipeline
    def slow(*a,**kw):
        time.sleep(0.12); return original(*a,**kw)
    monkeypatch.setattr(appmod,"run_multi_candidate_pipeline",slow)
    start=time.perf_counter(); r=client.post("/api/v1/runs",json={"task":bundle()["task"],"candidate":bundle()["candidate"],"experiment_spec":bundle()["experiment_spec"],"run_context":{"mode":"BENCHMARK"}},headers=hdr); elapsed=time.perf_counter()-start
    assert r.status_code==202 and r.json()["status"]=="QUEUED" and elapsed < 0.10
    first=client.get(r.json()["result_url"],headers=hdr).json(); assert first["status"] in {"QUEUED","RUNNING"}
    done,seen=poll(r.json()["result_url"],hdr); assert done["status"]=="COMPLETED" and any(x in {"QUEUED","RUNNING"} for x in seen+[first["status"]])


def test_async_failure_becomes_failed(monkeypatch):
    import backend.app as appmod
    hdr=headers(monkeypatch); RUN_STORE.clear()
    def boom(*a,**kw): raise RuntimeError("controlled-worker-failure")
    monkeypatch.setattr(appmod,"run_multi_candidate_pipeline",boom)
    b=bundle(); r=client.post("/api/v1/runs",json={"task":b["task"],"candidate":b["candidate"],"experiment_spec":b["experiment_spec"],"run_context":{"mode":"BENCHMARK"}},headers=hdr)
    got,_=poll(r.json()["result_url"],hdr)
    assert got["status"]=="FAILED" and "controlled-worker-failure" in got["error"]["message"]


# 24-25 Benchmark/LIVE契约来源与Private Gold隔离
def test_benchmark_and_live_contract_sources_are_separate(monkeypatch):
    hdr=headers(monkeypatch); RUN_STORE.clear(); b=bundle()
    rb=client.post("/api/v1/runs",json={"task":b["task"],"candidate":b["candidate"],"experiment_spec":b["experiment_spec"],"run_context":{"mode":"BENCHMARK"}},headers=hdr)
    gb,_=poll(rb.json()["result_url"],hdr); assert gb["evaluation_contract_source"]=="PRIVATE_GOLD"
    rl=client.post("/api/v1/runs",json=dynamic_payload("LIVE-SEPARATE"),headers=hdr)
    gl,_=poll(rl.json()["result_url"],hdr); assert gl["evaluation_contract_source"]=="LIVE_ACCEPTANCE_CONTRACT"


def test_live_poc_does_not_touch_case_registry(monkeypatch):
    import backend.app as appmod
    hdr=headers(monkeypatch); RUN_STORE.clear()
    def forbidden_registry(): raise AssertionError("LIVE_POC must not load Private Gold registry")
    monkeypatch.setattr(appmod,"get_case_registry",forbidden_registry)
    r=client.post("/api/v1/runs",json=dynamic_payload("LIVE-NO-GOLD"),headers=hdr)
    got,_=poll(r.json()["result_url"],hdr)
    assert got["status"]=="COMPLETED" and got["evaluation_contract_source"]=="LIVE_ACCEPTANCE_CONTRACT"

# 26 MOCK来源不得伪装为LIVE
def test_mock_top_level_relabel_live_is_rejected():
    b = bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="forge-mock")
    w["run_mode"] = "MOCK"
    w["source"].update({"kind": "MOCK", "provider": "mock-provider", "adapter_id": "mock-adapter", "reference": "mock-ref", "is_fixture": False, "is_mock": True, "fixture_reason": "mock test"})
    w["provenance"].update({"producer": "mock_executor", "environment": "LOCAL", "executor_type": "MOCK_EXECUTOR"})
    # 只篡改顶层标签，内部仍保留MOCK来源，应被LIVE一致性门禁拒绝。
    w["run_mode"] = "LIVE"
    w["source"].update({"kind": "LIVE_CAPTURE", "is_mock": False, "fixture_reason": None})
    w["provenance"].update({"producer": "claimed_live", "source_endpoint": "https://x", "environment": "PRODUCTION", "raw_response_ref": "sha256:x", "executor_type": "LIVE_EXECUTOR", "remote_execution_id": "r"})
    for group in ("latency", "cost", "token_usage"):
        for metric in w[group].values():
            if isinstance(metric, dict) and "availability" in metric:
                metric["source"] = "MOCK"
    with pytest.raises(SchemaValidationError, match="live_metric_source"):
        validate_workflow_result(w)


# 27 非法布尔值必须显式失败，不能Python truthy化
def test_invalid_boolean_string_is_rejected():
    payload={"state":"SUCCESS","result":{"action":"ANSWER","diagnosis":"TASK_COMPLETED","text":"ok","confidence":"MEDIUM","blocked":"not-a-bool"}}
    mapping=YuanqiResponseMapping(paths={"status":"state","output.final_action":"result.action","output.diagnosis_code":"result.diagnosis","output.response":"result.text","output.confidence":"result.confidence","output.guardrail_blocked":"result.blocked"})
    b=bundle(); adapter=YuanqiResponseAdapter(mapping)
    with pytest.raises(YuanqiMappingError, match="invalid_boolean:output.guardrail_blocked"):
        adapter.parse_with_context(payload,task=b["task"],candidate=b["candidate"],experiment_spec=b["experiment_spec"],run_id="bad-bool",source_endpoint="https://fake")


# 28 真实远端执行ID必须映射，不得用本地run_id冒充
def test_remote_execution_id_is_mapped_when_platform_provides_it():
    payload={"state":"SUCCESS","remote":{"id":"yuanqi-remote-777"},"result":{"action":"ANSWER","diagnosis":"TASK_COMPLETED","text":"ok","confidence":"MEDIUM"}}
    mapping=YuanqiResponseMapping(paths={"status":"state","remote_execution_id":"remote.id","output.final_action":"result.action","output.diagnosis_code":"result.diagnosis","output.response":"result.text","output.confidence":"result.confidence"})
    b=bundle(); parsed=YuanqiResponseAdapter(mapping).parse_with_context(payload,task=b["task"],candidate=b["candidate"],experiment_spec=b["experiment_spec"],run_id="local-123",source_endpoint="https://fake")
    assert parsed["provenance"]["remote_execution_id"] == "yuanqi-remote-777"
    assert parsed["source"]["reference"] == "yuanqi-remote-777"
    assert parsed["source"]["reference"] != parsed["run_id"]


# 29 多候选repeats也属于公平对照冻结参数
def test_multi_candidate_different_repeats_rejected(three_candidate_payload):
    p=deepcopy(three_candidate_payload)
    p["experiment_specs"][1]["repeats"] = 3
    with pytest.raises(ValueError, match="comparison_spec_mismatch:repeats"):
        run_multi_candidate_pipeline(p["task"],p["candidates"],p["experiment_specs"],registry=CaseRegistry())
