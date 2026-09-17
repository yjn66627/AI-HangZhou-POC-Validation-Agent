import json
from pathlib import Path

from backend.adapters.yuanqi import prepare_run_request, prepare_run_requests
from experiment.schemas import validate_candidate_plan, validate_experiment_spec, validate_task_input

ROOT=Path(__file__).resolve().parents[1]


def test_template_mapping_produces_valid_single_contracts():
    payload=json.loads((ROOT/'examples'/'yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json').read_text(encoding='utf-8'))
    bundle=prepare_run_request(payload)
    validate_task_input(bundle['task']); validate_candidate_plan(bundle['candidate']); validate_experiment_spec(bundle['experiment_spec'])
    assert bundle['experiment_spec']['execution_mode']=='LIVE'
    assert bundle['experiment_spec']['experiment_id']=='exp-live-demo'
    assert bundle['experiment_spec']['required_tools']==['tool_a']
    assert bundle['run_context']['mode']=='LIVE_POC'
    assert bundle['run_context']['live_acceptance_contract']['contract_id']=='live-demo-contract'
    assert '待真实字段联调' in bundle['task']['metadata']['platform_hint']


def test_template_mapping_supports_n_candidates():
    payload=json.loads((ROOT/'examples'/'yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json').read_text(encoding='utf-8'))
    payload['candidates'].append({**payload['candidates'][0], 'candidate_id':'cand-2','name':'候选2'})
    rows=prepare_run_requests(payload)
    assert len(rows['candidates']) == 2
    assert len(rows['candidates']) == len(rows['experiment_specs'])
    assert rows['experiment_specs'][0]['experiment_id']=='exp-live-demo-cand-1'
    assert rows['experiment_specs'][1]['experiment_id']=='exp-live-demo-cand-2'
