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
from experiment.evaluation_contract import compile_live_acceptance


def _template() -> dict[str, Any]:
    return json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))


def _acceptance(case_id: str) -> dict[str, Any]:
    return {
        "contract_id": f"empty-{case_id}",
        "allowed_actions": ["ANSWER"],
        "accepted_diagnoses": ["TASK_COMPLETED"],
        "required_tools": ["retrieve_context"],
        "allowed_tools": ["retrieve_context"],
        "forbidden_tools": [],
        "evidence_required": True,
        "should_escalate": False,
        "guardrail_required": False,
        "decision_criteria": {
            "source": "BUSINESS_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": 0.8},
            "cost": {"status": "REQUIRED", "max_value": 0.5, "currency": "CNY"},
            "latency": {"status": "REQUIRED", "max_ms": 5000},
        },
        "evidence_requirements": {"required_types": [], "required_claim_ids": [], "required_targets": [case_id], "require_tool_link": True, "require_action_result": True},
    }


def probe_available_tools() -> bool:
    p = _template(); candidates = {x for r in p["candidates"] for x in r.get("tools", [])}
    missing = deepcopy(p); missing["enterprise_requirement"].pop("available_tools", None)
    null = deepcopy(p); null["enterprise_requirement"]["available_tools"] = None
    empty = deepcopy(p); empty["enterprise_requirement"]["available_tools"] = []
    allow = deepcopy(p); allow["enterprise_requirement"]["available_tools"] = ["tool_a"]
    return (
        set(prepare_run_requests(missing)["task"]["available_tools"]) == candidates
        and set(prepare_run_requests(null)["task"]["available_tools"]) == candidates
        and prepare_run_requests(empty)["task"]["available_tools"] == []
        and prepare_run_requests(allow)["task"]["available_tools"] == ["tool_a"]
    )


def probe_required_tools() -> bool:
    p = _template()
    p["experiment_params"].pop("required_tools", None)
    missing = prepare_run_requests(p)["experiment_specs"][0]["required_tools"]
    p["experiment_params"]["required_tools"] = None
    null = prepare_run_requests(p)["experiment_specs"][0]["required_tools"]
    p["experiment_params"]["required_tools"] = []
    empty = prepare_run_requests(p)["experiment_specs"][0]["required_tools"]
    p["experiment_params"]["required_tools"] = ["tool_a"]
    allow = prepare_run_requests(p)["experiment_specs"][0]["required_tools"]
    return missing == null == empty == [] and allow == ["tool_a"]


def probe_allowed_actions() -> bool:
    base = _acceptance("A")
    missing = deepcopy(base); missing.pop("allowed_actions", None)
    null = deepcopy(base); null["allowed_actions"] = None
    empty = deepcopy(base); empty["allowed_actions"] = []
    one = deepcopy(base); one["allowed_actions"] = ["HANDOFF"]
    return (
        compile_live_acceptance("A", missing)["allowed_actions"] == ["ANSWER", "CLARIFY", "HANDOFF", "REFUSE"]
        and compile_live_acceptance("A", null)["allowed_actions"] == ["ANSWER", "CLARIFY", "HANDOFF", "REFUSE"]
        and compile_live_acceptance("A", empty)["allowed_actions"] == []
        and compile_live_acceptance("A", one)["allowed_actions"] == ["HANDOFF"]
    )


def probe_prohibited_operations() -> bool:
    p = _template(); sc = p["enterprise_requirement"]["safety_constraints"]
    sc["prohibited_operations"] = []
    return prepare_run_requests(p)["task"]["safety_constraints"]["prohibited_operations"] == []


def probe_business_constraints() -> bool:
    p = _template(); p["enterprise_requirement"]["business_constraints"] = {}
    return prepare_run_requests(p)["task"]["business_constraints"] == {}


def probe_success_criteria_zero() -> bool:
    p = _template(); p["experiment_params"]["success_criteria"]["max_cost"] = 0
    return prepare_run_requests(p)["experiment_specs"][0]["success_criteria"]["max_cost"] == 0


def probe_evidence_false() -> bool:
    c = _acceptance("E"); c["evidence_required"] = False
    return compile_live_acceptance("E", c)["evidence_required"] is False


def probe_boolean_false() -> bool:
    c = _acceptance("B"); c["should_escalate"] = "false"; c["guardrail_required"] = 0
    out = compile_live_acceptance("B", c)
    return out["should_escalate"] is False and out["guardrail_required"] is False


ROWS: list[dict[str, Any]] = [
    {"field":"available_tools","missing_null":"UNRESTRICTED（Adapter规范化为候选工具并集）","empty":"NONE_ALLOWED","false_zero":"N/A","probe":probe_available_tools},
    {"field":"required_tools","missing_null":"无显式强制工具","empty":"无显式强制工具","false_zero":"N/A","probe":probe_required_tools},
    {"field":"allowed_actions","missing_null":"默认Action集合","empty":"NONE_ALLOWED","false_zero":"N/A","probe":probe_allowed_actions},
    {"field":"prohibited_operations","missing_null":"无额外Task禁止项","empty":"无额外Task禁止项","false_zero":"N/A","probe":probe_prohibited_operations},
    {"field":"business_constraints","missing_null":"空约束集合","empty":"空约束集合","false_zero":"未知mandatory不得静默忽略","probe":probe_business_constraints},
    {"field":"success_criteria.max_cost","missing_null":"由Schema/业务规则决定","empty":"N/A","false_zero":"0为有效阈值，不得回退默认值","probe":probe_success_criteria_zero},
    {"field":"evidence_required","missing_null":"LIVE必须显式；Benchmark按公开样例契约","empty":"N/A","false_zero":"false保留为False并参与更严格合并","probe":probe_evidence_false},
    {"field":"should_escalate/guardrail_required","missing_null":"LIVE必须显式","empty":"N/A","false_zero":"false/0严格解析为False","probe":probe_boolean_false},
]


def audit() -> list[dict[str, Any]]:
    out=[]
    for row in ROWS:
        try:
            ok=bool(row["probe"]())
            note="PASS" if ok else "FAIL"
        except Exception as exc:  # pragma: no cover
            ok=False; note=f"ERROR:{type(exc).__name__}:{exc}"
        out.append({k:v for k,v in row.items() if k!="probe"} | {"status":note})
    return out


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines=[
        "# 空数组 / 缺失 / null 语义审计（v1.2.2）", "",
        "本审计只修复语义上会扩大权限、伪造默认值或改变验收标准的falsey混淆；不机械替换所有 `or default`。", "",
        "| 字段 | 缺失/null | 显式空数组/空对象 | false/0语义 | 行为验证 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['field']}` | {r['missing_null']} | {r['empty']} | {r['false_zero']} | {r['status']} |")
    lines += ["", f"总计：{len(rows)}项；FAIL={sum(r['status']!='PASS' for r in rows)}。", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    rows=audit()
    path=ROOT / "EMPTY_VALUE_SEMANTICS_AUDIT.md"
    path.write_text(render_markdown(rows),encoding="utf-8")
    bad=[r for r in rows if r["status"]!="PASS"]
    print(f"rows={len(rows)} failed={len(bad)} report={path.name}")
    raise SystemExit(1 if bad else 0)
