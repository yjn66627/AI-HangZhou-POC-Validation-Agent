from __future__ import annotations

import hashlib
import json
from pathlib import Path

from experiment.case_registry import CaseRegistry
from experiment.schemas import validate_task_input

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
CASE_ID = "TEST-P1"

OLD_PUBLIC_HASHES = {
    "TEST-R2": "d9302767b22a56072f27bacbc35c5d3561b8b5b5241cf9b69f0f8ac11b871048",
    "TEST-R3": "cec8f8b3a17b865609836fc169a0d8c1340086aeeae5b110db1807bada41e040",
    "TEST-I2": "5b4566e4f56008b3dbffa38c250ab49b277ce6194c73116b19262bf8f24d0dcd",
    "TEST-A2": "ea68b16eca3403c6f9d99c4431a12fa72f502c61f2da77253048b4c406ef05b6",
    "TEST-V2": "b692f1f2609ca8d092d00bee70bc9e0808f8d6840984b7a0550a332f0543cb6b",
}
TEST_P1_GOLD_CANONICAL_SHA256 = "17ff7e7f0bc02cb5402defe9f43800379cf117a93b3a1d712447ebd93c827866"

def _canonical_sha(row: dict) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _formal(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))

def test_zero_tool_case_is_registered_with_matching_private_gold():
    registry = CaseRegistry()
    public = registry.get_public_input(CASE_ID)
    gold = registry.get_private_gold(CASE_ID)
    assert public["case_id"] == gold["case_id"] == CASE_ID
    assert CASE_ID in registry.case_ids()

def test_zero_tool_public_case_has_no_tool_hint():
    public = CaseRegistry().get_public_input(CASE_ID)
    assert public["allowed_tools"] == []
    assert public["usage"] == "FORMAL_TEST_INPUT_ONLY"
    assert "不依赖实时外部信息" in public["known_context"]

def test_zero_tool_private_gold_has_no_tool_or_evidence_requirement():
    gold = CaseRegistry().get_private_gold(CASE_ID)
    expected = gold["expected"]
    assert expected["required_tools"] == []
    assert expected["allowed_tools"] == []
    assert expected["evidence_required"] is False
    assert expected["root_cause_must_be_evidenced"] is True

def test_zero_tool_private_gold_compiles_to_none_allowed_and_evidence_not_required():
    contract = CaseRegistry().build_evaluation_contract(CASE_ID)
    assert contract["required_tools"] == []
    assert contract["allowed_tools"] == []
    assert contract["tool_policy_mode"] == "NONE_ALLOWED"
    assert contract["evidence_required"] is False
    assert contract["root_cause_must_be_evidenced"] is True
    assert contract["required_checks"] == {
        "integration_proven": True,
        "quality_threshold_met": True,
        "cost_threshold_proven": False,
        "latency_threshold_proven": False,
        "full_business_acceptance_proven": False,
        "additional_measurement_required": True,
    }

def test_zero_tool_public_task_validates_against_registry_and_task_schema():
    public = CaseRegistry().get_public_input(CASE_ID)
    task = {
        "schema_version": "2.1",
        "task_id": "formal-zero-tool-test-p1",
        "case_id": CASE_ID,
        "user_query": public["user_query"],
        "visible_context": {"known_context": public["known_context"]},
        "available_docs": [],
        "available_tools": [],
        "safety_constraints": {
            "allow_write_operations": False,
            "require_evidence_for_dynamic_claims": False,
            "prohibited_operations": [],
        },
        "business_constraints": None,
        "metadata": {
            "source_dataset": "formal_test_inputs.json",
            "source_ref": CASE_ID,
            "platform_hint": None,
            "notes": "P1.3-A zero-tool formal case registry validation",
        },
    }
    validate_task_input(task)
    CaseRegistry().validate_public_task(task)

def test_old_five_public_cases_are_semantically_unchanged():
    data = _formal("formal_test_inputs.json")
    current = {row["case_id"]: _canonical_sha(row) for row in data["cases"] if row["case_id"] in OLD_PUBLIC_HASHES}
    assert current == OLD_PUBLIC_HASHES

def test_zero_tool_private_gold_case_is_semantically_unchanged_after_tool_policy_migration():
    data = _formal("formal_test_gold_private.json")
    row = next(row for row in data["cases"] if row["case_id"] == CASE_ID)
    assert _canonical_sha(row) == TEST_P1_GOLD_CANONICAL_SHA256

def test_formal_caseset_contains_exactly_old_five_plus_new_zero_tool_case():
    public_ids = {row["case_id"] for row in _formal("formal_test_inputs.json")["cases"]}
    gold_ids = {row["case_id"] for row in _formal("formal_test_gold_private.json")["cases"]}
    expected = set(OLD_PUBLIC_HASHES) | {CASE_ID}
    assert public_ids == gold_ids == expected

def test_fixture_assets_are_not_modified_by_formal_caseset_extension():
    assert hashlib.sha256((DATASETS / "fixture_inputs.json").read_bytes()).hexdigest() == "cd7a27df1612008d8ec4da70cdb4880600a5ea740bad6f61560fb8c53986adab"
    assert hashlib.sha256((DATASETS / "fixture_gold_private.json").read_bytes()).hexdigest() == "c971b43195ac473672ecba4cb4725166a4edaa577c5a36f39293abc0d4545e71"

def test_case_registry_code_is_unchanged():
    assert hashlib.sha256((ROOT / "experiment" / "case_registry.py").read_bytes()).hexdigest() == "00eb6489116db85ffe87e40b2d7a10ad4e9217d5cbe24f9d8cd968954bb0199d"


def test_zero_tool_case_evaluator_accepts_a_fully_compliant_static_decision_without_evidence():
    from experiment.evaluator import evaluate
    from experiment.experiment_runner import build_fixture_result

    registry = CaseRegistry()
    public = registry.get_public_input(CASE_ID)
    task = {
        "schema_version": "2.1",
        "task_id": "task-test-p1-eval",
        "case_id": CASE_ID,
        "user_query": public["user_query"],
        "visible_context": {"known_context": public["known_context"]},
        "available_docs": [],
        "available_tools": [],
        "safety_constraints": {
            "allow_write_operations": False,
            "require_evidence_for_dynamic_claims": False,
            "prohibited_operations": [],
        },
        "business_constraints": None,
        "metadata": {"source_dataset": "formal", "source_ref": CASE_ID, "platform_hint": None, "notes": None},
    }
    candidate = {
        "schema_version": "2.1",
        "candidate_id": "cand-test-p1-eval",
        "task_id": task["task_id"],
        "case_id": CASE_ID,
        "name": "zero-tool evaluator fixture",
        "approach_type": "LLM_ONLY",
        "summary": "仅用于验证Formal Gold/Evaluator零工具语义，不调用模型。",
        "model_provider": None,
        "model_name": None,
        "tools": [],
        "assumptions": [],
        "expected_strengths": [],
        "expected_risks": [],
        "estimated": None,
        "metadata": {"source_dataset": "test", "source_ref": CASE_ID, "platform_hint": None, "notes": "OFFLINE_TEST_ONLY"},
    }
    spec = {
        "schema_version": "2.1",
        "experiment_id": "exp-test-p1-eval",
        "task_id": task["task_id"],
        "case_id": CASE_ID,
        "candidate_id": candidate["candidate_id"],
        "execution_mode": "FIXTURE",
        "objective": "验证TEST-P1零工具、Evidence非必需的Evaluator语义。",
        "success_criteria": {
            "min_quality_score": 0.9,
            "max_latency_ms": None,
            "max_cost": None,
            "cost_currency": "CNY",
            "require_tool_trace": False,
            "require_evidence": False,
            "max_error_count": 0,
        },
        "required_tools": [],
        "prohibited_tools": [],
        "simulation": {"profile": "NORMAL_SUCCESS", "seed": 20260916},
        "business_constraints": {},
        "repeats": 1,
        "created_at": None,
    }
    workflow = build_fixture_result(task, candidate, spec, "run-test-p1-eval")
    workflow["output"].update({
        "response": "集成和质量已证明；成本、延迟口径及生产负载仍未证明，因此不能宣布完整商业验收通过，应补充对应测量。",
        "root_cause": None,
        "root_cause_evidence_refs": [],
        "checks": {
            "integration_proven": True,
            "quality_threshold_met": True,
            "cost_threshold_proven": False,
            "latency_threshold_proven": False,
            "full_business_acceptance_proven": False,
            "additional_measurement_required": True,
        },
    })
    workflow["evidence"] = []
    workflow["tool_trace"] = []
    result = evaluate(workflow, registry.build_evaluation_contract(CASE_ID), spec, task_input=task, candidate_plan=candidate)
    assert result["passed"] is True
    assert result["evidence"]["status"] == "NOT_REQUIRED"
    assert result["tool_trace"]["complete"] is True
    assert result["execution_plan_integrity"]["status"] == "PASS"
    assert result["unsupported_root_cause"] is False
