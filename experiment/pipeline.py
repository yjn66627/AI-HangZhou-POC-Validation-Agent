from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .case_registry import CaseRegistry
from .decision_engine import make_decision
from .evaluator import evaluate
from .executor_base import ExperimentExecutor
from .experiment_runner import run_experiment
from .policy_utils import parse_strict_bool
from .schemas import utc_now, validate_comparison_result, validate_evaluation_contract, validate_linked_inputs

DEFAULT_COMPARISON_RULES = {
    "minimum_pass_rate": 0.8,
    "maximum_failure_rate": 0.2,
    "maximum_timeout_rate": 0.2,
    "minimum_evidence_sufficiency_rate": 0.8,
    "allow_human_review": False,
    "base_currency": None,
    "fx_rates": {},
}


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    vals = sorted(values)
    return vals[max(0, math.ceil(0.95 * len(vals)) - 1)]


def _comparison_rules(value: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_COMPARISON_RULES)
    out.update(dict(value or {}))
    for key in ("minimum_pass_rate", "maximum_failure_rate", "maximum_timeout_rate", "minimum_evidence_sufficiency_rate"):
        out[key] = float(out[key])
        if not 0 <= out[key] <= 1:
            raise ValueError(f"comparison_rule_out_of_range:{key}")
    out["allow_human_review"] = parse_strict_bool(out["allow_human_review"], field_name="comparison_rules.allow_human_review")
    out["base_currency"] = None if out.get("base_currency") in {None, ""} else str(out.get("base_currency"))
    fx_rates = dict(out.get("fx_rates") or {})
    for currency, rate in fx_rates.items():
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or float(rate) <= 0:
            raise ValueError(f"invalid_fx_rate:{currency}")
    out["fx_rates"] = {str(k): float(v) for k, v in fx_rates.items()}
    return out


def _validate_fair_comparison(specs: Sequence[Mapping[str, Any]]) -> None:
    """同一comparison_group冻结成功标准；仅允许候选自身工具与simulation profile不同。"""
    if not specs:
        raise ValueError("experiment_specs_required")
    baseline = specs[0]
    frozen_fields = {
        "execution_mode": baseline["execution_mode"],
        "objective": baseline["objective"],
        "success_criteria": baseline["success_criteria"],
        "prohibited_tools": baseline["prohibited_tools"],
        "business_constraints": baseline["business_constraints"],
        "repeats": baseline["repeats"],
        "task_id": baseline["task_id"],
        "case_id": baseline["case_id"],
    }
    for spec in specs[1:]:
        for field, expected in frozen_fields.items():
            if spec[field] != expected:
                raise ValueError(f"comparison_spec_mismatch:{field}")


def aggregate_candidate(candidate_id: str, repeat_records: list[dict[str, Any]], rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rules = _comparison_rules(rules)
    evals = [r["evaluation_result"] for r in repeat_records]
    workflows = [r["workflow_result"] for r in repeat_records]
    decisions = [r["decision_card"] for r in repeat_records]
    qualities = [float(e["quality"]["score"]) for e in evals]
    latencies = [float(e["latency"]["value"]) for e in evals if e["latency"]["value"] is not None and e["latency"]["comparable"]]
    costs = [float(e["cost"]["value"]) for e in evals if e["cost"]["value"] is not None and e["cost"]["comparable"]]
    currencies = {e["cost"]["currency"] for e in evals if e["cost"]["value"] is not None and e["cost"]["comparable"]}
    pass_rate = sum(bool(e["passed"]) for e in evals) / len(evals)
    failure_rate = sum(w["status"] != "SUCCESS" for w in workflows) / len(workflows)
    timeout_rate = sum(w["status"] == "TIMEOUT" for w in workflows) / len(workflows)
    evidence_rate = sum(e["evidence"]["status"] in {"SUFFICIENT", "NOT_REQUIRED"} for e in evals) / len(evals)
    safety_violations = sum(bool(e["safety"]["violation"]) for e in evals)
    human_review_count = sum(bool(e["human_review"]["required"]) for e in evals)
    mandatory_escalation_count = sum(
        "evaluation_contract_requires_escalation" in e["human_review"].get("reasons", []) for e in evals
    )
    terminal_failure_count = sum(w["status"] == "CANCELLED" for w in workflows)
    execution_plan_violation_count = sum(e.get("execution_plan_integrity", {}).get("status") == "FAIL" for e in evals)
    decision_counts = Counter(d["decision"] for d in decisions)

    ineligible: list[str] = []
    if safety_violations:
        ineligible.append("safety_violation_present")
    if decision_counts.get("BLOCKED_BY_SAFETY", 0):
        ineligible.append("decision_blocked_by_safety")
    if mandatory_escalation_count:
        ineligible.append("mandatory_escalation_present")
    if terminal_failure_count:
        ineligible.append("terminal_failure_present")
    if execution_plan_violation_count:
        ineligible.append("execution_plan_violation_present")
    if human_review_count and not rules["allow_human_review"]:
        ineligible.append("human_review_required")
    if pass_rate < rules["minimum_pass_rate"]:
        ineligible.append("pass_rate_below_minimum")
    if failure_rate > rules["maximum_failure_rate"]:
        ineligible.append("failure_rate_above_maximum")
    if timeout_rate > rules["maximum_timeout_rate"]:
        ineligible.append("timeout_rate_above_maximum")
    if evidence_rate < rules["minimum_evidence_sufficiency_rate"]:
        ineligible.append("evidence_sufficiency_rate_below_minimum")
    # 普通DEFER/HUMAN_ASSISTED由通过率、失败率与allow_human_review控制；
    # 但证据不足属于实验结论不可用，仍作为硬门禁。
    if decision_counts.get("INSUFFICIENT_EVIDENCE", 0):
        ineligible.append("insufficient_evidence_decision_present")

    return {
        "candidate_id": candidate_id,
        "repeat_count": len(repeat_records),
        "pass_rate": round(pass_rate, 6),
        "quality_mean": round(statistics.fmean(qualities), 6),
        "quality_std": round(statistics.pstdev(qualities), 6) if len(qualities) > 1 else 0.0,
        "failure_rate": round(failure_rate, 6),
        "timeout_rate": round(timeout_rate, 6),
        "evidence_sufficiency_rate": round(evidence_rate, 6),
        "latency_mean_ms": round(statistics.fmean(latencies), 6) if latencies else None,
        "latency_p95_ms": round(_p95(latencies), 6) if latencies else None,
        "latency_available_rate": round(len(latencies) / len(evals), 6),
        "cost_mean": round(statistics.fmean(costs), 8) if costs else None,
        "cost_total": round(sum(costs), 8) if costs else None,
        "cost_currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "cost_available_rate": round(len(costs) / len(evals), 6),
        "tool_error_count": sum(1 for w in workflows for t in w["tool_trace"] if t["status"] == "ERROR"),
        "safety_block_count": int(decision_counts.get("BLOCKED_BY_SAFETY", 0)),
        "safety_violation_count": safety_violations,
        "human_review_count": human_review_count,
        "mandatory_escalation_count": mandatory_escalation_count,
        "terminal_failure_count": terminal_failure_count,
        "execution_plan_violation_count": execution_plan_violation_count,
        "decision_counts": dict(decision_counts),
        "eligible": not ineligible,
        "ineligibility_reasons": list(dict.fromkeys(ineligible)),
    }


def run_candidate_pipeline(
    task: Mapping[str, Any],
    candidate: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    master_run_id: str,
    evaluation_contract: Mapping[str, Any] | None = None,
    registry: CaseRegistry | None = None,
    executor: ExperimentExecutor | None = None,
    live_executor: ExperimentExecutor | None = None,
    comparison_rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_linked_inputs(task, candidate, spec)
    if evaluation_contract is None:
        if registry is None:
            raise ValueError("evaluation_contract_or_registry_required")
        evaluation_contract = registry.build_evaluation_contract(str(task["case_id"]))
    contract = validate_evaluation_contract(evaluation_contract)
    if contract["case_id"] != task["case_id"]:
        raise ValueError("evaluation_contract_case_id_mismatch")

    repeat_records: list[dict[str, Any]] = []
    for idx in range(1, int(spec.get("repeats", 1)) + 1):
        rid = f"{master_run_id}-{candidate['candidate_id']}-r{idx}"
        workflow = run_experiment(task, candidate, spec, run_id=rid, executor=executor, live_executor=live_executor)
        evaluation = evaluate(workflow, contract, spec, task, candidate)
        decision = make_decision(workflow, evaluation)
        repeat_records.append({"repeat_index": idx, "workflow_result": workflow, "evaluation_result": evaluation, "decision_card": decision})
    return {
        "candidate_id": candidate["candidate_id"],
        "experiment_id": spec["experiment_id"],
        "repeats": repeat_records,
        "aggregate": aggregate_candidate(candidate["candidate_id"], repeat_records, comparison_rules),
    }


def compare_candidates(
    case_id: str,
    candidate_results: Sequence[Mapping[str, Any]],
    *,
    comparison_id: str | None = None,
    comparison_rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rules = _comparison_rules(comparison_rules)
    summaries = [dict(row["aggregate"]) for row in candidate_results]
    eligible = [s for s in summaries if s["eligible"]]
    recommended: str | None = None
    rationale: list[str] = []

    currencies = {str(x["cost_currency"]) for x in eligible if x.get("cost_mean") is not None and x.get("cost_currency")}
    base_currency = rules.get("base_currency")
    fx_rates = dict(rules.get("fx_rates") or {})
    normalized_costs: dict[str, float] = {}
    if len(currencies) <= 1:
        cost_comparison_mode = "SAME_CURRENCY" if currencies else "NOT_AVAILABLE"
        comparison_currency = next(iter(currencies)) if currencies else None
        for row in eligible:
            if row.get("cost_mean") is not None:
                normalized_costs[str(row["candidate_id"])] = float(row["cost_mean"])
    elif base_currency and all(c == base_currency or c in fx_rates for c in currencies):
        cost_comparison_mode = "STATIC_FX"
        comparison_currency = str(base_currency)
        for row in eligible:
            if row.get("cost_mean") is None or not row.get("cost_currency"):
                continue
            currency = str(row["cost_currency"])
            multiplier = 1.0 if currency == base_currency else float(fx_rates[currency])
            normalized_costs[str(row["candidate_id"])] = float(row["cost_mean"]) * multiplier
    else:
        cost_comparison_mode = "COST_NOT_COMPARABLE"
        comparison_currency = None
        rationale.append("候选成本币种不同且未提供统一base_currency/fx_rates；本次排序不使用裸成本数值。")

    if eligible:
        def sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
            cid = str(row["candidate_id"])
            cost_rank = normalized_costs.get(cid, 0.0) if cost_comparison_mode != "COST_NOT_COMPARABLE" else 0.0
            latency = float(row["latency_p95_ms"] if row["latency_p95_ms"] is not None else (row["latency_mean_ms"] if row["latency_mean_ms"] is not None else float("inf")))
            return (
                -float(row["pass_rate"]),
                -float(row["quality_mean"]),
                -float(row["evidence_sufficiency_rate"]),
                float(row["failure_rate"]),
                cost_rank,
                latency,
                cid,
            )
        best = sorted(eligible, key=sort_key)[0]
        recommended = str(best["candidate_id"])
        cost_phrase = "统一币种成本" if cost_comparison_mode in {"SAME_CURRENCY", "STATIC_FX"} else "不使用跨币种裸成本"
        rationale.append(f"推荐{recommended}：Eligibility通过后按通过率、独立质量、Evidence充分率、失败率、{cost_phrase}、实际延迟确定性排序。")
        if best["cost_mean"] is None or best["latency_mean_ms"] is None or cost_comparison_mode == "COST_NOT_COMPARABLE":
            rationale.append("推荐仍存在成本/延迟不可比较项，结论仅为条件性推荐。")
    else:
        rationale.append("没有候选满足统一Eligibility门槛，当前不推荐任何候选。")
        for row in summaries:
            if row["ineligibility_reasons"]:
                rationale.append(f"{row['candidate_id']}不合格：{','.join(row['ineligibility_reasons'])}")

    eligible_ids = [str(row["candidate_id"]) for row in summaries if row["eligible"]]
    ineligible_rows = [
        {"candidate_id": str(row["candidate_id"]), "reasons": list(row["ineligibility_reasons"])}
        for row in summaries if not row["eligible"]
    ]
    ranking_reason = (
        f"Eligibility后按pass_rate↓、independent quality↓、Evidence充分率↓、failure_rate↑、cost({cost_comparison_mode})、latency↑、candidate_id排序。"
        if recommended else "无候选通过统一Eligibility门禁，因此不执行可推荐候选排序。"
    )
    result = {
        "schema_version": "1.4",
        "comparison_id": comparison_id or f"cmp-{uuid4().hex[:12]}",
        "case_id": case_id,
        "candidate_summaries": summaries,
        "eligible_candidates": eligible_ids,
        "ineligible_candidates": ineligible_rows,
        "recommended_candidate_id": recommended,
        "recommendation": "优先候选仅用于后续受控实验/人工决策，不代表已上线。" if recommended else "当前无可推荐候选。",
        "ranking_reason": ranking_reason,
        "cost_comparison": [{"candidate_id": str(row["candidate_id"]), "mean": row["cost_mean"], "currency": row["cost_currency"], "available_rate": row["cost_available_rate"], "normalized_mean": normalized_costs.get(str(row["candidate_id"])), "comparison_currency": comparison_currency, "comparable": cost_comparison_mode != "COST_NOT_COMPARABLE"} for row in summaries],
        "cost_comparison_status": cost_comparison_mode,
        "cost_comparison_currency": comparison_currency,
        "latency_comparison": [{"candidate_id": str(s["candidate_id"]), "mean_ms": s["latency_mean_ms"], "p95_ms": s["latency_p95_ms"], "available_rate": s["latency_available_rate"]} for s in summaries],
        "quality_comparison": [{"candidate_id": str(s["candidate_id"]), "mean": s["quality_mean"], "std": s["quality_std"], "pass_rate": s["pass_rate"]} for s in summaries],
        "evidence_comparison": [{"candidate_id": str(s["candidate_id"]), "sufficiency_rate": s["evidence_sufficiency_rate"]} for s in summaries],
        "safety_summary": [{"candidate_id": str(s["candidate_id"]), "safety_violation_count": s["safety_violation_count"], "safety_block_count": s["safety_block_count"], "human_review_count": s["human_review_count"], "mandatory_escalation_count": s["mandatory_escalation_count"], "terminal_failure_count": s["terminal_failure_count"], "execution_plan_violation_count": s["execution_plan_violation_count"]} for s in summaries],
        "decision_summary": {str(s["candidate_id"]): dict(s["decision_counts"]) for s in summaries},
        "rationale": rationale,
        "eligibility_rules": rules,
        "generated_at": utc_now(),
    }
    return validate_comparison_result(result)


def run_multi_candidate_pipeline(
    task: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    specs: Sequence[Mapping[str, Any]],
    *,
    master_run_id: str | None = None,
    evaluation_contract: Mapping[str, Any] | None = None,
    registry: CaseRegistry | None = None,
    executor: ExperimentExecutor | None = None,
    live_executor: ExperimentExecutor | None = None,
    comparison_rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not candidates or len(candidates) != len(specs):
        raise ValueError("candidates_and_specs_must_be_same_nonzero_length")
    _validate_fair_comparison(specs)
    master_run_id = master_run_id or f"run-{uuid4().hex[:12]}"
    spec_by_candidate = {str(s["candidate_id"]): s for s in specs}
    if len(spec_by_candidate) != len(specs):
        raise ValueError("duplicate_candidate_id_in_specs")
    results = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        if cid not in spec_by_candidate:
            raise ValueError(f"missing_experiment_spec_for_candidate:{cid}")
        results.append(
            run_candidate_pipeline(
                task,
                candidate,
                spec_by_candidate[cid],
                master_run_id=master_run_id,
                evaluation_contract=evaluation_contract,
                registry=registry,
                executor=executor,
                live_executor=live_executor,
                comparison_rules=comparison_rules,
            )
        )
    comparison = compare_candidates(str(task["case_id"]), results, comparison_id=f"cmp-{master_run_id}", comparison_rules=comparison_rules)
    return {
        "run_id": master_run_id,
        "status": "COMPLETED",
        "case_id": task["case_id"],
        "candidate_results": results,
        "comparison_result": comparison,
    }
