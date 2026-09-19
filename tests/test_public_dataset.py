from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_INPUTS = ROOT / "datasets" / "formal_test_inputs.json"


def _public_inputs() -> dict:
    return json.loads(PUBLIC_INPUTS.read_text(encoding="utf-8"))


def test_public_formal_input_dataset_is_present_and_well_formed():
    data = _public_inputs()

    assert data["usage"] == "EXECUTOR_VISIBLE_FORMAL_INPUT"
    assert isinstance(data["cases"], list) and data["cases"]
    assert len({row["case_id"] for row in data["cases"]}) == len(data["cases"])

    for row in data["cases"]:
        assert isinstance(row["case_id"], str) and row["case_id"]
        assert isinstance(row["user_query"], str) and row["user_query"]
        assert isinstance(row["known_context"], str) and row["known_context"]
        assert isinstance(row["allowed_tools"], list)


def test_public_formal_inputs_do_not_expose_evaluation_fields():
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
