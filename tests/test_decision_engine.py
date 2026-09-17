import json
from pathlib import Path

from experiment.decision_engine import make_decision
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={'fx-success':'SUPPORT_CONTROLLED_TRIAL','fx-quality':'HUMAN_ASSISTED','fx-timeout':'HUMAN_ASSISTED','fx-evidence':'HUMAN_ASSISTED','fx-risk':'BLOCKED_BY_SAFETY'}


def test_five_fixture_decisions_are_deterministic():
    for name,expected in EXPECTED.items():
        b=json.loads((ROOT/'examples'/f'{name}_bundle.json').read_text(encoding='utf-8'))
        w=run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id=f'run-{name}')
        e=evaluate(w,b['case_spec'],b['experiment_spec']); d=make_decision(w,e)
        assert d['decision']==expected
