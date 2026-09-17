import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from experiment.experiment_runner import run_experiment
from experiment.schemas import (
    SchemaValidationError,
    load_schema,
    validate_candidate_plan,
    validate_experiment_spec,
    validate_task_input,
    validate_workflow_result,
)

ROOT = Path(__file__).resolve().parents[1]


def bundles():
    for path in sorted((ROOT / "examples").glob("fx-*_bundle.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def test_all_seven_schemas_are_valid_draft_202012():
    names = ["task_input.schema.json", "candidate_plan.schema.json", "experiment_spec.schema.json", "workflow_result.schema.json", "evaluation_result.schema.json", "decision_card.schema.json", "comparison_result.schema.json", "evaluation_contract.schema.json"]
    for name in names:
        Draft202012Validator.check_schema(load_schema(name))


def test_all_fixture_inputs_validate():
    for b in bundles():
        validate_task_input(b["task"]); validate_candidate_plan(b["candidate"]); validate_experiment_spec(b["experiment_spec"])


def test_fixture_cannot_masquerade_as_live():
    b = next(bundles())
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="run-mask")
    forged = deepcopy(w)
    forged["run_mode"] = "LIVE"
    forged["source"].update({"kind": "BACKEND", "is_fixture": False, "is_mock": False, "fixture_reason": None, "provider": "fake", "adapter_id": "fake", "reference": "fake"})
    forged["provenance"].update({"environment": "PRODUCTION", "source_endpoint": "https://example.invalid/run"})
    with pytest.raises(SchemaValidationError, match="live_.*fixture|live_requires_live_executor_type"):
        validate_workflow_result(forged)


def test_missing_required_field_rejected():
    b = next(bundles()); broken = deepcopy(b["task"]); del broken["available_tools"]
    with pytest.raises(SchemaValidationError): validate_task_input(broken)


def test_estimated_metric_requires_note_and_source(success_bundle):
    w = run_experiment(success_bundle["task"], success_bundle["candidate"], success_bundle["experiment_spec"], run_id="metric-est")
    w["cost"]["total"] = {"value": 0.02, "availability": "ESTIMATED", "source": None, "note": None}
    with pytest.raises(SchemaValidationError): validate_workflow_result(w)
