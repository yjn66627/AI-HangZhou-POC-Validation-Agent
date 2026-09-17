import json
from pathlib import Path

from experiment.case_registry import CaseRegistry
from experiment.error_analysis import analyze_evaluations
from experiment.pipeline import run_multi_candidate_pipeline

ROOT=Path(__file__).resolve().parents[1]


def test_full_fixture_pipeline_five_cases():
    evals=[]
    for path in sorted((ROOT/'examples').glob('fx-*_bundle.json')):
        b=json.loads(path.read_text(encoding='utf-8'))
        record=run_multi_candidate_pipeline(b['task'],[b['candidate']],[b['experiment_spec']],registry=CaseRegistry(),master_run_id=f"e2e-{b['task']['case_id'].lower()}")
        evals.append(record['candidate_results'][0]['repeats'][0]['evaluation_result'])
    analysis=analyze_evaluations(evals)
    assert analysis['sample_count']==5
    assert analysis['pass_count']==1
