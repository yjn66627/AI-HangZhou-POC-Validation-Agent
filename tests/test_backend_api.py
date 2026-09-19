import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import RUN_STORE, app

ROOT=Path(__file__).resolve().parents[1]
client=TestClient(app)


def load(name='fx-success'):
    b=json.loads((ROOT/'examples'/f'{name}_bundle.json').read_text(encoding='utf-8'))
    return {'task':b['task'],'candidate':b['candidate'],'experiment_spec':b['experiment_spec'],'run_context':{'mode':'BENCHMARK'}}


def poll(url,headers,timeout=3.0):
    deadline=time.time()+timeout
    seen=[]
    while time.time()<deadline:
        r=client.get(url,headers=headers); assert r.status_code==200
        body=r.json(); seen.append(body['status'])
        if body['status'] in {'COMPLETED','FAILED'}: return body,seen
        time.sleep(0.01)
    raise AssertionError('run_not_finished')


def test_health():
    r=client.get('/health'); assert r.status_code==200 and r.json()['status']=='ok' and r.json()['version']=='1.2.3'


def test_missing_api_key_rejected(monkeypatch):
    monkeypatch.setenv('API_KEY','secret')
    r=client.post('/api/v1/runs',json=load())
    assert r.status_code==401


def test_wrong_api_key_rejected(monkeypatch):
    monkeypatch.setenv('API_KEY','secret')
    r=client.post('/api/v1/runs',json=load(),headers={'Authorization':'Bearer wrong'})
    assert r.status_code==403


def test_server_without_api_key_is_misconfigured(monkeypatch):
    monkeypatch.delenv('API_KEY',raising=False)
    r=client.post('/api/v1/runs',json=load(),headers={'Authorization':'Bearer anything'})
    assert r.status_code==503


def test_post_then_get_returns_full_chain(api_headers):
    RUN_STORE.clear(); created=client.post('/api/v1/runs',json=load(),headers=api_headers)
    assert created.status_code==202
    body=created.json(); assert body['status']=='QUEUED'
    result,seen=poll(body['result_url'],api_headers)
    assert result['status']=='COMPLETED'
    assert result['workflow_result']['run_mode']=='FIXTURE'
    assert result['evaluation_result']['quality']['source']=='INDEPENDENT_RULES'
    assert result['decision_card']['decision']=='SUPPORT_CONTROLLED_TRIAL'
    assert result['comparison_result']['recommended_candidate_id']==load()['candidate']['candidate_id']
    assert result['evaluation_contract_source'] != 'LIVE_ACCEPTANCE_CONTRACT'
    assert seen[0] in {'QUEUED','RUNNING','COMPLETED'}


def test_live_disabled_by_config_becomes_failed(api_headers):
    payload=load(); payload['run_context']={'mode':'BENCHMARK'}
    payload['experiment_spec']['execution_mode']='LIVE'; payload['experiment_spec']['simulation']['profile']=None
    r=client.post('/api/v1/runs',json=payload,headers=api_headers)
    assert r.status_code==202
    got,_=poll(r.json()['result_url'],api_headers)
    assert got['status']=='FAILED'
    assert 'disabled' in got['error']['message']


def test_multi_candidate_api(three_candidate_payload,api_headers):
    RUN_STORE.clear(); payload={**three_candidate_payload,'run_context':{'mode':'BENCHMARK'}}
    r=client.post('/api/v1/runs',json=payload,headers=api_headers)
    assert r.status_code==202
    got,_=poll(r.json()['result_url'],api_headers)
    assert got['status']=='COMPLETED'
    assert len(got['candidate_results'])==3
    assert got['comparison_result']['recommended_candidate_id']=='cand-compare-1'
    assert got['workflow_result'] is None


def test_api_rejects_case_id_borrowing(api_headers):
    payload=load(); payload['task']['user_query']='另一条问题，不应复用FX-SUCCESS私有Gold。'
    r=client.post('/api/v1/runs',json=payload,headers=api_headers)
    assert r.status_code==422
    assert 'public_case_input_mismatch' in r.json()['detail']
