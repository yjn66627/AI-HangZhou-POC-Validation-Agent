from copy import deepcopy

import pytest

from experiment.experiment_runner import run_experiment
from experiment.schemas import SchemaValidationError, validate_workflow_result


def workflow(success_bundle, rid="adv"):
    return run_experiment(success_bundle["task"],success_bundle["candidate"],success_bundle["experiment_spec"],run_id=rid)


def test_token_internal_mismatch_rejected(success_bundle):
    w=workflow(success_bundle,"tok"); w["token_usage"]["total_tokens"]["value"] += 1
    with pytest.raises(SchemaValidationError,match="token_total_component_mismatch"): validate_workflow_result(w)


def test_cost_internal_mismatch_rejected(success_bundle):
    w=workflow(success_bundle,"cost"); w["cost"]["total"]["value"] = 999
    with pytest.raises(SchemaValidationError,match="cost_total_component_mismatch"): validate_workflow_result(w)


def test_latency_internal_mismatch_rejected(success_bundle):
    w=workflow(success_bundle,"lat"); w["latency"]["total_ms"]["value"] = 99999
    with pytest.raises(SchemaValidationError,match="latency_total_component_mismatch"): validate_workflow_result(w)


def test_not_provided_metric_must_have_null_value(success_bundle):
    w=workflow(success_bundle,"np"); w["latency"]["model_ms"]={"value":12,"availability":"NOT_PROVIDED","source":"X","note":None}
    with pytest.raises(SchemaValidationError): validate_workflow_result(w)
