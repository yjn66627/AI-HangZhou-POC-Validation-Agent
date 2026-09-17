from copy import deepcopy

from experiment.case_registry import CaseRegistry
from experiment.pipeline import run_multi_candidate_pipeline
from experiment.schemas import validate_comparison_result


def test_repeats_one(success_bundle):
    result=run_multi_candidate_pipeline(success_bundle['task'],[success_bundle['candidate']],[success_bundle['experiment_spec']],registry=CaseRegistry(),master_run_id='repeat1')
    c=result['candidate_results'][0]
    assert len(c['repeats'])==1 and c['aggregate']['repeat_count']==1


def test_repeats_three_aggregates(success_bundle):
    spec=deepcopy(success_bundle['experiment_spec']); spec['repeats']=3
    result=run_multi_candidate_pipeline(success_bundle['task'],[success_bundle['candidate']],[spec],registry=CaseRegistry(),master_run_id='repeat3')
    agg=result['candidate_results'][0]['aggregate']
    assert agg['repeat_count']==3
    assert agg['quality_mean']==1.0
    assert agg['quality_std']==0.0
    assert agg['pass_rate']==1.0


def test_three_candidate_comparison(three_candidate_payload):
    p=three_candidate_payload
    result=run_multi_candidate_pipeline(p['task'],p['candidates'],p['experiment_specs'],registry=CaseRegistry(),master_run_id='multi')
    cmp=result['comparison_result']; validate_comparison_result(cmp)
    assert len(cmp['candidate_summaries'])==3
    assert cmp['recommended_candidate_id']=='cand-compare-1'


def test_no_eligible_candidate_does_not_mislabel_as_safety_block():
    from experiment.pipeline import compare_candidates

    candidate_results = [
        {
            "aggregate": {
                "candidate_id": "cand-partial",
                "repeat_count": 1,
                "pass_rate": 0.0,
                "quality_mean": 0.75,
                "quality_std": 0.0,
                "failure_rate": 1.0,
                "evidence_sufficiency_rate": 1.0,
                "latency_mean_ms": 800.0,
                "latency_p95_ms": 800.0,
                "latency_available_rate": 1.0,
                "cost_mean": 0.02,
                "cost_total": 0.02,
                "cost_currency": "CNY",
                "cost_available_rate": 1.0,
                "tool_error_count": 0,
                "safety_block_count": 0,
                "timeout_rate": 0.0,
                "human_review_count": 0,
                "safety_violation_count": 0,
                "mandatory_escalation_count": 0,
                "terminal_failure_count": 0,
                "execution_plan_violation_count": 0,
                "decision_counts": {"DEFER": 1},
                "eligible": False,
                "ineligibility_reasons": ["pass_rate_below_minimum"],
            }
        }
    ]
    cmp = compare_candidates("FX-SUCCESS", candidate_results, comparison_id="cmp-no-pass")
    assert cmp["recommended_candidate_id"] is None
    text = " ".join(cmp["rationale"])
    assert "没有候选满足统一Eligibility门槛" in text
    assert "所有候选均触发安全阻断" not in text
