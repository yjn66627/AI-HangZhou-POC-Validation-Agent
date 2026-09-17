import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'datasets'
N=D/'normalized'


def test_dataset_counts_and_public_private_separation():
    dev=json.loads((N/'development_cases.json').read_text(encoding='utf-8'))
    formal_inputs=json.loads((D/'formal_test_inputs.json').read_text(encoding='utf-8'))
    formal_gold=json.loads((D/'formal_test_gold_private.json').read_text(encoding='utf-8'))
    kb=json.loads((N/'background_knowledge.json').read_text(encoding='utf-8'))
    assert len(dev['cases'])==6 and len(formal_inputs['cases'])==6 and len(formal_gold['cases'])==6 and len(kb)==13
    assert {x['case_id'] for x in formal_inputs['cases']} == {x['case_id'] for x in formal_gold['cases']}


def test_formal_inputs_do_not_contain_gold_fields():
    forbidden={'expected_behavior','expected_behavior_raw','prohibited_behavior','prohibited_behavior_raw','acceptance_criteria','acceptance_criteria_raw','expected'}
    data=json.loads((D/'formal_test_inputs.json').read_text(encoding='utf-8'))
    for row in data['cases']:
        assert not forbidden.intersection(row)


def test_formal_private_gold_does_not_contain_user_query_or_context():
    data=json.loads((D/'formal_test_gold_private.json').read_text(encoding='utf-8'))
    for row in data['cases']:
        assert 'user_query' not in row and 'known_context' not in row


def test_combined_formal_file_retired():
    assert not (N/'formal_test_cases.json').exists()
    assert (D/'history'/'formal_test_cases_combined_v1.0_DO_NOT_USE.json').exists()


def test_dify_development_history_never_claims_yuanqi_live():
    data=json.loads((N/'development_cases.json').read_text(encoding='utf-8'))
    for row in data['cases']:
        assert row['source_platform'].startswith('Dify')
        assert row['live_claim_allowed'] is False
