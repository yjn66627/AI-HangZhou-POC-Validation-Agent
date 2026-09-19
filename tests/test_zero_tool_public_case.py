from __future__ import annotations

import json
from pathlib import Path

from experiment.case_registry import CaseRegistry
from experiment.schemas import validate_task_input


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
CASE_ID = "TEST-P1"


def _public_inputs() -> dict:
    return json.loads((DATASETS / "formal_test_inputs.json").read_text(encoding="utf-8"))


def test_zero_tool_public_case_has_no_tool_hint():
    public = CaseRegistry().get_public_input(CASE_ID)

    assert public["case_id"] == CASE_ID
    assert public["allowed_tools"] == []
    assert public["usage"] == "FORMAL_TEST_INPUT_ONLY"
    assert "不依赖实时外部信息" in public["known_context"]


def test_zero_tool_public_task_validates_against_registry_and_schema():
    public = CaseRegistry().get_public_input(CASE_ID)
    task = {
        "schema_version": "2.1",
        "task_id": "formal-zero-tool-public-test",
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
            "notes": "public zero-tool input validation",
        },
    }

    validate_task_input(task)
    CaseRegistry().validate_public_task(task)


def test_public_formal_caseset_contains_the_zero_tool_case():
    data = _public_inputs()
    case_ids = {row["case_id"] for row in data["cases"]}

    assert CASE_ID in case_ids
    assert len(case_ids) == len(data["cases"])


def test_public_formal_cases_only_expose_input_fields():
    forbidden = {
        "expected_behavior",
        "expected_behavior_raw",
        "prohibited_behavior",
        "prohibited_behavior_raw",
        "acceptance_criteria",
        "acceptance_criteria_raw",
        "expected",
    }

    for row in _public_inputs()["cases"]:
        assert not forbidden.intersection(row)
