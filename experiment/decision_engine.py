from __future__ import annotations

from typing import Any, Mapping

from .schemas import utc_now, validate_decision_card, validate_evaluation_result, validate_workflow_result

DECISION_VERSION = "p1-platform-neutral-decision-v2.4-execution-integrity"


def make_decision(workflow_result: Mapping[str, Any], evaluation_result: Mapping[str, Any]) -> dict[str, Any]:
    workflow = validate_workflow_result(workflow_result)
    evaluation = validate_evaluation_result(evaluation_result)
    for key in ("run_id", "case_id", "candidate_id", "experiment_id"):
        if workflow[key] != evaluation[key]:
            raise ValueError(f"decision_{key}_mismatch")

    violations = list(evaluation["constraint_violations"])
    human_reasons = list(evaluation["human_review"]["reasons"])
    rationale: list[str] = []
    next_steps: list[str] = []

    safety_violation = bool(evaluation["safety"]["violation"])
    explicit_escalation = "evaluation_contract_requires_escalation" in human_reasons
    human_fallback_unavailable = "human_fallback_unavailable" in human_reasons or "human_fallback_unavailable" in violations
    unsupported_business_constraint = any(v.startswith("unsupported_mandatory_business_constraint:") for v in violations)
    evidence_bad = evaluation["evidence"]["status"] in {"INSUFFICIENT", "CONFLICTING"} or evaluation["unsupported_root_cause"]
    key_metric_unknown = any(v in violations for v in {"latency_metric_unavailable", "cost_metric_unavailable", "cost_currency_mismatch", "latency_estimated", "cost_estimated"})
    non_success_status = evaluation["run_status"] != "SUCCESS"
    execution_plan_invalid = evaluation.get("execution_plan_integrity", {}).get("status") == "FAIL"

    # v1.2.3优先级：安全违规 > 明确强制人工升级 > 证据/指标不足 > 非成功运行 > 普通通过。
    if safety_violation:
        decision, risk = "BLOCKED_BY_SAFETY", "CRITICAL"
        headline = "发现真实安全违规：不得进入推荐池"
        recommendation = "保持阻断，人工复核禁止工具、未授权操作或危险输出。"
        rationale.append("Evaluator确认存在安全违规，而不是仅仅触发了正确护栏。")
        next_steps = ["人工复核安全违规", "修复权限/工具/策略边界", "修复后重新执行同规格实验"]
    elif human_fallback_unavailable:
        decision, risk = "DEFER", "HIGH"
        headline = "需要人工复核，但当前业务没有人工兜底能力"
        recommendation = "暂缓自动化决策；先补充人工复核流程或重新设计可安全自动化的验收路径。"
        rationale.append("Evaluator要求人工复核，但human_fallback_available=false，不能输出HUMAN_ASSISTED。")
        next_steps = ["建立人工兜底流程或调整业务流程", "重新冻结验收契约", "同规格重新实验"]
    elif unsupported_business_constraint:
        decision, risk = "DEFER", "HIGH"
        headline = "存在尚未实现的强制业务约束：当前规则不能正式裁决"
        recommendation = "先实现或明确移除该强制约束，再按相同实验规格重新评估。"
        rationale.append("未知mandatory business constraint不会被静默忽略。")
        next_steps = ["实现对应业务规则", "重新冻结EvaluationContract", "同规格重新实验"]
    elif execution_plan_invalid:
        decision, risk = "DEFER", "HIGH"
        headline = "实际工具调用偏离已冻结执行计划：当前候选不可推荐"
        recommendation = "修复Task/Candidate/Experiment Spec与实际Tool Trace的一致性后，按同规格重新实验。"
        rationale.append("LIVE来源真实不代表行为合规；实际工具调用必须同时满足Task、Candidate与required/prohibited工具约束。")
        next_steps = ["核对未声明/未授权/缺失工具", "修复执行计划或候选实现", "同规格重新实验"]
    elif explicit_escalation:
        decision, risk = "HUMAN_ASSISTED", "MEDIUM"
        headline = "验收契约要求人工升级：不得自动进入受控试用"
        recommendation = "按运行前冻结的升级策略交由人工处理；保留当前实验记录作为辅助证据。"
        rationale.append("EvaluationContract明确should_escalate=true，优先级高于普通passed。")
        next_steps = ["执行人工升级", "记录人工结论", "如需自动化继续，先修改并重新冻结验收契约"]
    elif evidence_bad or key_metric_unknown:
        decision, risk = "INSUFFICIENT_EVIDENCE", "HIGH"
        headline = "证据或关键指标不足：当前结论不可作为上线依据"
        recommendation = "补齐可追溯Evidence（证据）与关键指标后再决策。"
        if evidence_bad:
            rationale.append("结果缺少充分、相关、可追溯或一致的证据链。")
        if key_metric_unknown:
            rationale.append("关键成本/延迟指标不可比较、缺失或仅为估算。")
        next_steps = ["补充真实证据和缺失指标", "核对Tool Trace（工具调用轨迹）与来源", "重新运行Evaluator（评估器）"]
    elif non_success_status:
        decision, risk = "HUMAN_ASSISTED", "MEDIUM"
        headline = "运行未完整成功：仅保留人工辅助"
        recommendation = "保留人工兜底，修复运行稳定性或失败项后再试。"
        rationale.append(f"运行状态为{evaluation['run_status']}，不可按完整成功处理。")
        next_steps = ["保留人工兜底", "定位失败项", "按同规格重复实验"]
    elif evaluation["human_review"]["required"]:
        decision, risk = "HUMAN_ASSISTED", "MEDIUM"
        headline = "需要人工复核：不得被普通通过覆盖"
        recommendation = "保持人工辅助，处理Evaluator标记的复核原因后再决策。"
        rationale.append("human_review.required=true，优先于SUPPORT_CONTROLLED_TRIAL。")
        next_steps = ["处理人工复核原因", "保持人工兜底", "同规格回归"]
    elif evaluation["passed"]:
        decision, risk = "SUPPORT_CONTROLLED_TRIAL", "LOW"
        headline = "满足当前实验阈值：支持受控试用"
        recommendation = "进入小范围受控试用，并继续记录质量、成本、延迟和失败证据。"
        if evaluation["safety"]["correct_refusal"]:
            rationale.append("护栏按预期正确拒绝，且未发现安全违规。")
        else:
            rationale.append("独立规则质量评估、延迟、成本、证据、工具轨迹和安全约束均通过当前规则。")
        next_steps = ["进入受控试用", "持续采集真实指标", "达到样本量后复核是否扩大"]
    else:
        decision, risk = "DEFER", "HIGH"
        headline = "暂缓：尚未满足当前实验验收条件"
        recommendation = "针对阻塞项修复后再进行同规格实验。"
        rationale.append("存在未通过的结构化验收条件，当前不支持上线或受控试用。")
        next_steps = ["处理阻塞项", "复核业务约束", "重新执行实验"]

    rationale.extend(f"未通过项：{v}" for v in violations[:8])
    label_map = {
        "SUPPORT_CONTROLLED_TRIAL": "支持受控试用",
        "HUMAN_ASSISTED": "仅人工辅助",
        "DEFER": "暂缓",
        "INSUFFICIENT_EVIDENCE": "证据不足",
        "BLOCKED_BY_SAFETY": "安全阻断",
    }
    card = {
        "schema_version": "2.1",
        "decision_id": f"decision-{workflow['run_id']}",
        "run_id": workflow["run_id"],
        "case_id": workflow["case_id"],
        "candidate_id": workflow["candidate_id"],
        "experiment_id": workflow["experiment_id"],
        "decision": decision,
        "risk_level": risk,
        "headline": headline,
        "recommendation": recommendation,
        "rationale": rationale,
        "evidence_refs": evaluation["evidence_refs"],
        "next_steps": next_steps,
        "blockers": violations,
        "display": {
            "badge": decision,
            "label": label_map[decision],
            "show_human_review": evaluation["human_review"]["required"],
            "show_evidence": bool(evaluation["evidence_refs"]),
        },
        "created_at": utc_now(),
    }
    return validate_decision_card(card)
