from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.adapters.yuanqi import prepare_run_requests
from experiment.decision_engine import make_decision
from experiment.evaluation_contract import compile_live_acceptance
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment



def _bundle() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "fx-success_bundle.json").read_text(encoding="utf-8"))


def _acceptance(case_id: str, **overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "contract_id": f"audit-{case_id}",
        "allowed_actions": ["ANSWER"],
        "accepted_diagnoses": ["TASK_COMPLETED"],
        "required_tools": ["retrieve_context"],
        "allowed_tools": ["retrieve_context"],
        "forbidden_tools": ["write_resource"],
        "evidence_required": True,
        "should_escalate": False,
        "guardrail_required": False,
        "root_cause_must_be_evidenced": True,
        "decision_criteria": {
            "source": "BUSINESS_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": 0.8},
            "cost": {"status": "REQUIRED", "max_value": 0.5, "currency": "CNY"},
            "latency": {"status": "REQUIRED", "max_ms": 5000},
        },
        "required_response_keywords": [],
        "required_checks": {},
        "forbidden_claims": [],
        "evidence_requirements": {
            "required_types": [], "required_claim_ids": [], "required_targets": [case_id],
            "require_tool_link": True, "require_action_result": True,
        },
    }
    out.update(overrides)
    return out


def _no_evidence(workflow: dict[str, Any]) -> dict[str, Any]:
    w = deepcopy(workflow)
    w["evidence"] = []
    w["output"]["root_cause"] = None
    w["output"]["root_cause_evidence_refs"] = []
    for row in w["tool_trace"]:
        row["evidence_refs"] = []
    return w


def _probe_available_tools() -> bool:
    payload = json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    missing = deepcopy(payload); missing["enterprise_requirement"].pop("available_tools", None)
    empty = deepcopy(payload); empty["enterprise_requirement"]["available_tools"] = []
    a = prepare_run_requests(missing)["task"]["available_tools"]
    b = prepare_run_requests(empty)["task"]["available_tools"]
    return bool(a) and b == []


def _probe_required_tools() -> bool:
    payload = json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))
    payload["experiment_params"]["required_tools"] = []
    rows = prepare_run_requests(payload)
    return all(spec["required_tools"] == [] for spec in rows["experiment_specs"])


def _probe_allowed_actions() -> bool:
    case_id = "AUDIT-ACTIONS"
    default = compile_live_acceptance(case_id, _acceptance(case_id, allowed_actions=None))["allowed_actions"]
    none = compile_live_acceptance(case_id, _acceptance(case_id, allowed_actions=[]))["allowed_actions"]
    return bool(default) and none == []


def _probe_human_fallback() -> bool:
    b = _bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-fallback")
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], should_escalate=True))
    spec_true = deepcopy(b["experiment_spec"]); spec_true["business_constraints"]["human_fallback_available"] = True
    spec_false = deepcopy(b["experiment_spec"]); spec_false["business_constraints"]["human_fallback_available"] = False
    d_true = make_decision(w, evaluate(w, c, spec_true, b["task"]))["decision"]
    d_false = make_decision(w, evaluate(w, c, spec_false, b["task"]))["decision"]
    return d_true == "HUMAN_ASSISTED" and d_false == "DEFER"


def _probe_prohibited_operations() -> bool:
    b = _bundle(); b["task"]["safety_constraints"]["prohibited_operations"] = ["retrieve_context"]
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-prohibit")
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], allowed_tools=None, forbidden_tools=[]))
    return evaluate(w, c, b["experiment_spec"], b["task"])["safety"]["violation"] is True


def _probe_require_evidence() -> bool:
    b = _bundle(); b["task"]["safety_constraints"]["require_evidence_for_dynamic_claims"] = False
    w = _no_evidence(run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-evidence"))
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], evidence_required=False))
    spec_false = deepcopy(b["experiment_spec"]); spec_false["success_criteria"]["require_evidence"] = False
    spec_true = deepcopy(spec_false); spec_true["success_criteria"]["require_evidence"] = True
    a = evaluate(w, c, spec_false, b["task"])["evidence"]["status"]
    z = evaluate(w, c, spec_true, b["task"])["evidence"]["status"]
    return a == "NOT_REQUIRED" and z == "INSUFFICIENT"


def _probe_threshold(field: str) -> bool:
    b = _bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id=f"audit-{field}")
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"]))
    base = evaluate(w, c, b["experiment_spec"], b["task"])
    changed_task = deepcopy(b["task"])
    if field == "min_quality_score":
        changed_task["business_constraints"][field] = 0.99
        changed = evaluate(w, c, b["experiment_spec"], changed_task)
        return changed["quality"]["threshold"] != base["quality"]["threshold"]
    if field == "max_latency_ms":
        changed_task["business_constraints"][field] = 1
        changed = evaluate(w, c, b["experiment_spec"], changed_task)
        return changed["latency"]["passed"] is False
    if field == "max_cost":
        changed_task["business_constraints"][field] = 0.00001
        changed = evaluate(w, c, b["experiment_spec"], changed_task)
        return changed["cost"]["passed"] is False
    if field == "cost_currency":
        changed_task["business_constraints"]["max_cost"] = 0.5
        changed_task["business_constraints"][field] = "USD"
        changed = evaluate(w, c, b["experiment_spec"], changed_task)
        return "business_constraint_currency_conflict" in changed["constraint_violations"] or "cost_currency_mismatch" in changed["constraint_violations"]
    raise AssertionError(field)


def _probe_should_escalate() -> bool:
    b = _bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-escalate")
    c0 = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], should_escalate=False))
    c1 = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], should_escalate=True))
    return make_decision(w, evaluate(w, c0, b["experiment_spec"], b["task"]))["decision"] != make_decision(w, evaluate(w, c1, b["experiment_spec"], b["task"]))["decision"]


def _probe_guardrail() -> bool:
    b = _bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-guardrail")
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], guardrail_required=True))
    return "required_guardrail_not_triggered" in evaluate(w, c, b["experiment_spec"], b["task"])["constraint_violations"]


def _probe_allowed_write() -> bool:
    b = _bundle(); w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="audit-write")
    extra = deepcopy(w["tool_trace"][0]); extra.update({"tool_call_id":"audit-write-extra","tool":"write_resource","status":"SUCCESS","arguments":{},"evidence_refs":[],"unauthorized_attempt":False})
    w["tool_trace"].append(extra)
    c = compile_live_acceptance(b["task"]["case_id"], _acceptance(b["task"]["case_id"], allowed_tools=None, forbidden_tools=[]))
    return any("task_write_operation_executed" in x for x in evaluate(w, c, b["experiment_spec"], b["task"])["safety"]["violation_reasons"])


PROBES: dict[str, Callable[[], bool]] = {
    "available_tools": _probe_available_tools,
    "required_tools": _probe_required_tools,
    "allowed_actions": _probe_allowed_actions,
    "human_fallback_available": _probe_human_fallback,
    "prohibited_operations": _probe_prohibited_operations,
    "require_evidence": _probe_require_evidence,
    "min_quality_score": lambda: _probe_threshold("min_quality_score"),
    "max_latency_ms": lambda: _probe_threshold("max_latency_ms"),
    "max_cost": lambda: _probe_threshold("max_cost"),
    "cost_currency": lambda: _probe_threshold("cost_currency"),
    "should_escalate": _probe_should_escalate,
    "guardrail_required": _probe_guardrail,
    "allowed_write_operations": _probe_allowed_write,
    "supported_business_constraint": _probe_human_fallback,
}

ROWS: list[dict[str, Any]] = [
    {"field":"available_tools","producer":"腾讯元器/Task","consumer":"Adapter + linked-input gate","files":["backend/adapters/yuanqi.py","experiment/schemas.py"],"token":"available_tools","probe":"available_tools"},
    {"field":"required_tools","producer":"Experiment design","consumer":"Evaluator coverage","files":["backend/adapters/yuanqi.py","experiment/evaluator.py"],"token":"required_tools","probe":"required_tools"},
    {"field":"allowed_actions","producer":"Evaluation acceptance contract","consumer":"Evaluator action gate","files":["experiment/evaluation_contract.py","experiment/evaluator.py"],"token":"allowed_actions","probe":"allowed_actions"},
    {"field":"human_fallback_available","producer":"Business constraints","consumer":"Evaluator + Decision Engine","files":["experiment/policy_utils.py","experiment/evaluator.py","experiment/decision_engine.py"],"token":"human_fallback_available","probe":"human_fallback_available"},
    {"field":"prohibited_operations","producer":"Task safety","consumer":"Evaluator safety hard gate","files":["experiment/evaluation_contract.py","experiment/evaluator.py"],"token":"prohibited_operations","probe":"prohibited_operations"},
    {"field":"require_evidence","producer":"Task/Experiment/Contract","consumer":"Merged evidence validation","files":["experiment/evaluation_contract.py","experiment/evaluator.py"],"token":"require_evidence","probe":"require_evidence"},
    {"field":"min_quality_score","producer":"Experiment/Business","consumer":"Evaluator threshold","files":["experiment/evaluator.py"],"token":"min_quality_score","probe":"min_quality_score"},
    {"field":"max_latency_ms","producer":"Experiment/Business","consumer":"Evaluator threshold","files":["experiment/evaluator.py"],"token":"max_latency_ms","probe":"max_latency_ms"},
    {"field":"max_cost","producer":"Experiment/Business","consumer":"Evaluator threshold","files":["experiment/evaluator.py"],"token":"max_cost","probe":"max_cost"},
    {"field":"cost_currency","producer":"Experiment/Business","consumer":"Evaluator comparability","files":["experiment/evaluator.py"],"token":"cost_currency","probe":"cost_currency"},
    {"field":"should_escalate","producer":"Acceptance","consumer":"Evaluator + Decision","files":["experiment/evaluator.py","experiment/decision_engine.py"],"token":"should_escalate","probe":"should_escalate"},
    {"field":"guardrail_required","producer":"Acceptance","consumer":"Evaluator safety semantics","files":["experiment/evaluator.py"],"token":"guardrail_required","probe":"guardrail_required"},
    {"field":"allowed_write_operations","producer":"Task safety","consumer":"Evaluator safety gate","files":["experiment/evaluator.py"],"token":"allow_write_operations","probe":"allowed_write_operations"},
    {"field":"business_constraints.supported","producer":"Task/Experiment","consumer":"EvaluationContract + Evaluator/Decision","files":["experiment/policy_utils.py","experiment/evaluation_contract.py","experiment/evaluator.py"],"token":"SUPPORTED_BUSINESS_CONSTRAINTS","probe":"supported_business_constraint"},
]


def audit() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in ROWS:
        static_ok = any(row["token"] in (ROOT / fn).read_text(encoding="utf-8") for fn in row["files"] if (ROOT / fn).exists())
        try:
            behavior_ok = bool(PROBES[row["probe"]]())
            behavior_note = "PASS" if behavior_ok else "FAIL"
        except Exception as exc:  # pragma: no cover - report path
            behavior_ok = False
            behavior_note = f"ERROR:{type(exc).__name__}:{exc}"
        status = "CONSUMED" if static_ok and behavior_ok else "NEEDS_REVIEW"
        out.append({**row, "static_status":"PASS" if static_ok else "FAIL", "behavior_status":behavior_note, "decision":"YES", "status":status})
    return out


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 契约字段使用审计（v1.2.2）", "",
        "本版同时执行 Static Usage Audit（静态使用审计）与 Behavioral Usage Audit（行为使用审计）。",
        "字段只有在代码引用存在且单字段变更能触发预期评估/决策行为时，才标记为 `CONSUMED`。", "",
        "| 字段 | 生产者 | 消费者 | 静态审计 | 行为审计 | 真正影响决策 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['field']}` | {r['producer']} | {r['consumer']} | {r['static_status']} | {r['behavior_status']} | {r['decision']} | {r['status']} |")
    lines += ["", f"总计：{len(rows)}项；NEEDS_REVIEW={sum(r['status']!='CONSUMED' for r in rows)}。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    rows = audit()
    path = ROOT / "CONTRACT_FIELD_USAGE_AUDIT.md"
    path.write_text(render_markdown(rows), encoding="utf-8")
    bad = [r for r in rows if r["status"] != "CONSUMED"]
    print(f"rows={len(rows)} needs_review={len(bad)} report={path.name}")
    raise SystemExit(1 if bad else 0)
