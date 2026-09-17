from __future__ import annotations

from experiment.case_registry import CaseRegistry
from experiment.experiment_runner import FixtureExecutor, build_fixture_result
from experiment.pipeline import run_candidate_pipeline


class SpyExecutor(FixtureExecutor):
    def __init__(self): self.seen=[]
    def execute(self, *, task, candidate, experiment_spec, run_id):
        serialized=str({'task':task,'candidate':candidate,'experiment_spec':experiment_spec})
        for forbidden in ['expected_behavior','acceptance_criteria','prohibited_behavior','private_gold','evidence_keywords','required_response_keywords']:
            assert forbidden not in serialized
        self.seen.append(serialized)
        return build_fixture_result(task,candidate,experiment_spec,run_id)


def test_registry_separates_public_and_private():
    r=CaseRegistry()
    public=r.get_public_input('FX-SUCCESS'); private=r.get_private_gold('FX-SUCCESS')
    assert 'expected' not in public
    assert 'expected' in private


def test_private_gold_never_enters_executor(success_bundle):
    spy=SpyExecutor(); registry=CaseRegistry()
    out=run_candidate_pipeline(success_bundle['task'],success_bundle['candidate'],success_bundle['experiment_spec'],registry=registry,master_run_id='gold-leak',executor=spy)
    assert spy.seen and out['repeats'][0]['evaluation_result']['quality']['source']=='INDEPENDENT_RULES'


def test_registry_rejects_case_id_borrowing(success_bundle):
    registry=CaseRegistry()
    task=dict(success_bundle['task'])
    task['user_query']='这是另一条完全不同的问题，不能借用FX-SUCCESS的Gold。'
    import pytest
    from experiment.case_registry import CaseRegistryError
    with pytest.raises(CaseRegistryError, match='public_case_input_mismatch:FX-SUCCESS:user_query'):
        registry.validate_public_task(task)
