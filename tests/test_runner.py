import json
from copy import deepcopy
from pathlib import Path

import pytest

from experiment.executor_base import LiveExecutionUnavailable
from experiment.experiment_runner import run_experiment
from experiment.schemas import validate_workflow_result

ROOT=Path(__file__).resolve().parents[1]


def load(case): return json.loads((ROOT/'examples'/f'{case}_bundle.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name',['fx-success','fx-quality','fx-timeout','fx-evidence','fx-risk'])
def test_runner_outputs_contract_valid_workflow_result(name):
    b=load(name); result=run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id=f'run-{name}')
    validate_workflow_result(result)
    assert result['provenance']['environment']=='SANDBOX'
    assert result['run_mode'] in {'FIXTURE','CONTROLLED_FAULT'}


def test_live_requires_injected_executor():
    b=load('fx-success'); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(LiveExecutionUnavailable): run_experiment(b['task'],b['candidate'],b['experiment_spec'])


def test_metrics_missing_is_legal_not_zero():
    b=load('fx-success'); b['experiment_spec']['simulation']['profile']='METRICS_MISSING'
    r=run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='missing')
    assert r['cost']['total']['value'] is None and r['cost']['total']['availability']=='NOT_PROVIDED'
    assert r['token_usage']['total_tokens']['value'] is None
