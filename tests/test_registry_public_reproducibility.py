"""Explicit synthetic examples; no historical expected answers are mounted."""
from __future__ import annotations

import importlib
import json
import time
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.schemas import RunRequest
from experiment.case_registry import CaseRegistry, CaseRegistryError
from experiment.experiment_runner import FixtureExecutor, build_fixture_result
from experiment.pipeline import run_multi_candidate_pipeline

pytestmark = pytest.mark.synthetic_registry
DATA = Path(__file__).parent / "fixtures" / "synthetic_registry"
CASE = "SYNTHETIC-R4-REGISTRY-001"
backend_app = importlib.import_module("backend.app")
client = TestClient(backend_app.app)


def request_data():
    return json.loads((DATA / "request.json").read_text(encoding="utf-8"))["request"]


def registry(with_rules=True):
    return CaseRegistry(public_files=[DATA / "public_inputs.json"],
                        private_files=[DATA / "evaluation_rules.json"] if with_rules else [])


def poll(url, headers):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {"COMPLETED", "FAILED"}:
            return result
        time.sleep(0.01)
    pytest.fail("synthetic run did not finish")


def test_fixture_is_independent_synthetic_data_and_schema_valid():
    for name in ("request.json", "public_inputs.json", "evaluation_rules.json"):
        assert json.loads((DATA / name).read_text(encoding="utf-8"))["data_origin"] == "SYNTHETIC_DEMO_DATA"
    payload = request_data()
    RunRequest.model_validate(payload)
    assert payload["task"]["case_id"] == CASE
    assert "SYNTHETIC_DEMO_DATA" in payload["task"]["user_query"]


def test_public_inputs_and_explicit_evaluation_rules_are_separate():
    loaded = registry()
    public = loaded.get_public_input(CASE)
    rules = loaded.get_private_gold(CASE)
    assert "expected" not in public
    assert rules["data_origin"] == "SYNTHETIC_DEMO_DATA"
    assert rules["expected"]["allowed_actions"] == ["CLARIFY"]
    assert loaded.case_ids() == {CASE}


def test_no_evaluation_mount_is_fail_closed():
    loaded = registry(with_rules=False)
    assert loaded.get_public_input(CASE)["case_id"] == CASE
    assert loaded.private_files == []
    with pytest.raises(CaseRegistryError, match="private_gold_not_found"):
        loaded.build_evaluation_contract(CASE)


def test_duplicate_public_case_is_rejected():
    with pytest.raises(CaseRegistryError, match="duplicate_case_id"):
        CaseRegistry(public_files=[DATA / "public_inputs.json", DATA / "public_inputs.json"], private_files=[])


@pytest.mark.parametrize("field,value", [("user_query", "tampered synthetic query"), ("visible_context", {}), ("available_tools", [])])
def test_public_input_binding_rejects_tampering(field, value):
    task = request_data()["task"]
    registry().validate_public_task(task)
    task[field] = value
    with pytest.raises(CaseRegistryError, match="public_case_input_mismatch"):
        registry().validate_public_task(task)


def test_explicit_arbitrary_rule_is_compiled_without_default_dataset():
    loaded = registry()
    contract = loaded.build_evaluation_contract(CASE)
    assert contract["case_id"] == CASE
    assert contract["allowed_actions"] == ["CLARIFY"]
    assert contract["evidence_required"] is True
    assert loaded.private_files == [DATA / "evaluation_rules.json"]


class RecordingExecutor(FixtureExecutor):
    def __init__(self):
        self.seen = []

    def execute(self, *, task, candidate, experiment_spec, run_id):
        seen = deepcopy({"task": task, "candidate": candidate, "experiment_spec": experiment_spec})
        text = json.dumps(seen)
        for forbidden in ('"expected":', '"evaluation_contract":', '"private_gold":', '"accepted_diagnoses":'):
            assert forbidden not in text
        self.seen.append(seen)
        return build_fixture_result(task, candidate, experiment_spec, run_id)


def execute(repeats=1):
    payload = request_data()
    payload["experiment_spec"]["repeats"] = repeats
    executor = RecordingExecutor()
    result = run_multi_candidate_pipeline(payload["task"], [payload["candidate"]], [payload["experiment_spec"]],
                                          registry=registry(), master_run_id="synthetic-r4-local", executor=executor)
    return result, executor


def test_executor_does_not_receive_rules_and_evaluator_rejects_mismatched_action():
    result, executor = execute()
    assert len(executor.seen) == 1
    repeat = result["candidate_results"][0]["repeats"][0]
    assert repeat["workflow_result"]["run_mode"] == "FIXTURE"
    assert repeat["workflow_result"]["output"]["final_action"] != "CLARIFY"
    evaluation = repeat["evaluation_result"]
    assert evaluation["passed"] is False
    assert any("action" in x for x in evaluation["constraint_violations"])
    assert result["comparison_result"]["recommended_candidate_id"] is None


def test_synthetic_repeats_are_aggregated_without_claiming_measurement():
    result, executor = execute(repeats=3)
    row = result["candidate_results"][0]
    assert len(executor.seen) == len(row["repeats"]) == row["aggregate"]["repeat_count"] == 3
    assert all(r["evaluation_result"]["passed"] is False for r in row["repeats"])
    assert row["aggregate"]["eligible"] is False
    assert result["comparison_result"]["recommended_candidate_id"] is None


def test_benchmark_api_correctly_rejects_missing_evaluation_rules(api_headers, monkeypatch):
    monkeypatch.setattr(backend_app, "get_case_registry", lambda: registry(with_rules=False))
    before = set(backend_app.RUN_STORE)
    response = client.post("/api/v1/runs", json=request_data(), headers=api_headers)
    assert response.status_code == 422
    assert "private_gold_not_found" in response.json()["detail"]
    assert set(backend_app.RUN_STORE) == before


def test_explicit_synthetic_benchmark_runs_but_does_not_fake_policy_success(api_headers, monkeypatch):
    monkeypatch.setattr(backend_app, "get_case_registry", registry)
    response = client.post("/api/v1/runs", json=request_data(), headers=api_headers)
    assert response.status_code == 202
    result = poll(response.json()["result_url"], api_headers)
    assert result["status"] == "COMPLETED"
    assert result["evaluation_result"]["passed"] is False
    assert result["comparison_result"]["recommended_candidate_id"] is None
    assert result["workflow_result"]["run_mode"] == "FIXTURE"
