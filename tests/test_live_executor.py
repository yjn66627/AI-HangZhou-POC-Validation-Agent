from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from backend.live_executor import ExternalApiLiveExecutor, PassthroughWorkflowResultAdapter
from experiment.executor_base import ExecutorAuthenticationError, ExecutorResponseError, ExecutorTimeoutError, LiveExecutionUnavailable
from experiment.experiment_runner import run_experiment


def make_live_result(success_bundle, run_id):
    b=deepcopy(success_bundle)
    w=run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id=run_id)
    w['run_mode']='LIVE'
    w['source'].update({'kind':'LIVE_CAPTURE','provider':'fake-live-server','adapter_id':'test-adapter','reference':'remote-'+run_id,'is_fixture':False,'is_mock':False,'fixture_reason':None})
    for group in ('latency','cost','token_usage'):
        for value in w[group].values():
            if isinstance(value,dict) and 'availability' in value:
                value['source']='fake-live-server'
    w['quality_metrics']['candidate_reported_score']['source']='fake-live-server'
    for call in w['tool_trace']:
        call['latency_ms']['source']='fake-live-server'
        call['source']='fake-live-server'
    for ev in w['evidence']:
        ev['source']='fake-live-server'
    w['provenance'].update({'producer':'fake_live_server','adapter_id':'test-adapter','source_endpoint':'https://fake.local/run','environment':'STAGING','raw_response_ref':'sha256:fake','raw_response_source':'fake-live-server','executor_type':'LIVE_EXECUTOR','remote_execution_id':'remote-'+run_id})
    w['timestamps'].update({'remote_availability':'AVAILABLE','received_at':w['timestamps']['finished_at']})
    return w


def test_live_executor_mock_success(success_bundle):
    def handler(request):
        body=__import__('json').loads(request.content.decode())
        return httpx.Response(200,json=make_live_result(success_bundle,body['run_id']))
    client=httpx.Client(transport=httpx.MockTransport(handler))
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key='k',response_adapter=PassthroughWorkflowResultAdapter(),client=client)
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    w=run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-ok',live_executor=ex)
    assert w['run_mode']=='LIVE' and w['source']['is_fixture'] is False


def test_live_executor_timeout(success_bundle):
    def handler(request): raise httpx.ReadTimeout('boom',request=request)
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key='k',response_adapter=PassthroughWorkflowResultAdapter(),client=httpx.Client(transport=httpx.MockTransport(handler)))
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(ExecutorTimeoutError): run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-timeout',live_executor=ex)


def test_live_executor_invalid_json(success_bundle):
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key='k',response_adapter=PassthroughWorkflowResultAdapter(),client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,text='not-json'))))
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(ExecutorResponseError): run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-json',live_executor=ex)


def test_live_executor_network_error(success_bundle):
    def handler(request): raise httpx.ConnectError('offline',request=request)
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key='k',response_adapter=PassthroughWorkflowResultAdapter(),client=httpx.Client(transport=httpx.MockTransport(handler)))
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(LiveExecutionUnavailable): run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-net',live_executor=ex)


def test_live_executor_missing_auth(success_bundle):
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key=None,response_adapter=PassthroughWorkflowResultAdapter())
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(ExecutorAuthenticationError): run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-auth',live_executor=ex)


def test_live_executor_remote_auth_rejected(success_bundle):
    ex=ExternalApiLiveExecutor(endpoint='https://fake.local/run',api_key='bad',response_adapter=PassthroughWorkflowResultAdapter(),client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'detail':'bad'}))))
    b=deepcopy(success_bundle); b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    with pytest.raises(ExecutorAuthenticationError): run_experiment(b['task'],b['candidate'],b['experiment_spec'],run_id='live-401',live_executor=ex)


def test_yuanqi_field_mapping_missing_metrics_becomes_not_provided(success_bundle):
    from backend.adapters.yuanqi import YuanqiResponseAdapter, YuanqiResponseMapping
    payload={
        'state':'SUCCESS',
        'result':{'action':'ANSWER','diagnosis':'TASK_COMPLETED','text':'受控完成','confidence':'MEDIUM'},
    }
    mapping=YuanqiResponseMapping(paths={
        'status':'state','output.final_action':'result.action','output.diagnosis_code':'result.diagnosis','output.response':'result.text','output.confidence':'result.confidence'
    })
    adapter=YuanqiResponseAdapter(mapping)
    b=deepcopy(success_bundle)
    b['experiment_spec']['execution_mode']='LIVE'; b['experiment_spec']['simulation']['profile']=None
    parsed=adapter.parse_with_context(payload,task=b['task'],candidate=b['candidate'],experiment_spec=b['experiment_spec'],run_id='mapped-live',source_endpoint='https://fake.local')
    assert parsed['cost']['total']['availability']=='NOT_PROVIDED'
    assert parsed['latency']['total_ms']['value'] is None
    assert parsed['token_usage']['total_tokens']['availability']=='NOT_PROVIDED'
