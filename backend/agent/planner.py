from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from experiment.schemas import utc_now

from .llm_client import AgentLlmError, classify_intent_llm, complete_intake_json, llm_configured


_SMALL_TALK_EXACT = {
    "你好", "您好", "嗨", "哈喽", "hello", "hi", "hey",
    "早上好", "下午好", "晚上好", "晚安", "谢谢", "感谢", "谢谢你",
    "你是谁", "你叫什么", "讲个笑话", "天气怎么样", "在吗", "在嘛",
    "你好呀", "你好啊", "早上好呀", "嗯", "哦", "好的", "ok",
}

_SMALL_TALK_PREFIXES = ("你好", "您好", "hello", "hi", "hey", "嗨")

_VALIDATION_HINTS = (
    "上生产", "上线", "poc", "验证", "实验", "质量门槛", "质量分",
    "成本", "延迟", "试运行", "能不能上", "客服", "知识库",
    "达标", "并发", "稳定性", "证据", "对照",
)


def classify_intent(goal: str, *, allow_llm: bool = True) -> str:
    text = (goal or "").strip()
    if not text:
        return "CHAT"
    if _has_validation_hint(text):
        return "INTAKE"
    if is_small_talk(text):
        return "CHAT"
    if len(text) <= 24:
        return "CHAT"
    if allow_llm and llm_configured():
        try:
            return classify_intent_llm(text)
        except AgentLlmError:
            pass
    return "INTAKE"


def is_small_talk(goal: str) -> bool:
    """Keep greetings and social turns out of the validation pipeline."""
    text = (goal or "").strip()
    normalized = re.sub(r"[，。！？!?、,.；;：:~～\s]+", "", text.lower())
    if not normalized:
        return True
    if _has_validation_hint(text):
        return False
    if normalized in _SMALL_TALK_EXACT or normalized in {"你好吗", "最近怎么样", "聊聊天", "陪我聊聊"}:
        return True
    return any(normalized.startswith(prefix) for prefix in _SMALL_TALK_PREFIXES) and len(normalized) <= 12


def _has_validation_hint(text: str) -> bool:
    blob = text.lower()
    return any(hint.lower() in blob for hint in _VALIDATION_HINTS)


def _extract_numeric_targets(goal: str, constraints: list[str]) -> dict[str, Any]:
    blob = " ".join([goal, *constraints])
    quality = 0.8
    quality_match = re.search(
        r"(?:质量(?:门槛|分|分数)?|min_quality_score|quality)[^\d]{0,12}(0(?:\.\d+)?|1(?:\.0+)?)",
        blob,
        flags=re.I,
    )
    if quality_match:
        quality = float(quality_match.group(1))
    cost = None
    currency = None
    cost_match = re.search(
        r"(?:成本|预算|max_cost)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(元|CNY|USD)?",
        blob,
        flags=re.I,
    )
    if cost_match:
        cost = float(cost_match.group(1))
        raw_currency = (cost_match.group(2) or "CNY").upper()
        currency = "CNY" if raw_currency in {"元", "CNY"} else raw_currency
    latency = None
    latency_match = re.search(
        r"(?:延迟|时延|max_latency)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:ms|毫秒)?",
        blob,
        flags=re.I,
    )
    if latency_match:
        latency = float(latency_match.group(1))
    return {
        "min_quality_score": quality,
        "max_cost": cost,
        "cost_currency": currency,
        "max_latency_ms": latency,
    }


def _deterministic_sketch(goal: str, constraints: list[str]) -> dict[str, Any]:
    extracted = _extract_numeric_targets(goal, constraints)
    unproven = []
    if extracted["max_cost"] is None:
        unproven.append("真实货币成本")
    if extracted["max_latency_ms"] is None:
        unproven.append("延迟口径")
    unproven.extend(["生产并发", "长期稳定性"])
    return {
        "proven": ["需求已被收成 Formal Case", "将进行系统路径与错误外推 Baseline 的对照"],
        "unproven": unproven,
        "min_quality_score": extracted["min_quality_score"],
        "max_cost": extracted["max_cost"],
        "cost_currency": extracted["cost_currency"],
        "max_latency_ms": extracted["max_latency_ms"],
        "tools": ["retrieve_context"],
        "notes": constraints,
    }


FORBIDDEN_CLAIM_PHRASES = ("可以上生产", "生产可用", "成本可控", "Production Ready")


def _sanitize_claims(items: list[str]) -> list[str]:
    cleaned = []
    for item in items:
        text = str(item).strip()
        if text and not any(phrase in text for phrase in FORBIDDEN_CLAIM_PHRASES):
            cleaned.append(text)
    return cleaned


def _merge_llm_sketch(goal: str, constraints: list[str]) -> tuple[dict[str, Any], str]:
    if not llm_configured():
        return _deterministic_sketch(goal, constraints), "DETERMINISTIC"
    try:
        raw = complete_intake_json(goal, constraints)
    except AgentLlmError:
        return _deterministic_sketch(goal, constraints), "DETERMINISTIC_FALLBACK"
    sketch = _deterministic_sketch(goal, constraints)
    proven = _sanitize_claims([str(x) for x in raw.get("proven") or []])
    unproven = _sanitize_claims([str(x) for x in raw.get("unproven") or []])
    if proven:
        sketch["proven"] = proven
    if unproven:
        sketch["unproven"] = unproven
    for key in ("min_quality_score", "max_cost", "max_latency_ms"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            sketch[key] = float(value)
    if isinstance(raw.get("cost_currency"), str) and raw["cost_currency"].strip():
        sketch["cost_currency"] = raw["cost_currency"].strip()
    if isinstance(raw.get("tools"), list) and raw["tools"]:
        sketch["tools"] = [str(x) for x in raw["tools"] if str(x).strip()]
    return sketch, "LLM"


def compile_intake(goal: str, constraints: list[str] | None = None) -> dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal_required")
    constraints = [str(x).strip() for x in (constraints or []) if str(x).strip()]
    sketch, source = _merge_llm_sketch(goal, constraints)
    suffix = uuid4().hex[:8]
    case_id = f"INTAKE-{suffix}"
    task_id = f"task-{suffix}"
    now = utc_now()
    tools = sketch["tools"] or ["retrieve_context"]
    quality = float(sketch["min_quality_score"] or 0.8)
    cost_applicable = sketch["max_cost"] is not None
    latency_applicable = sketch["max_latency_ms"] is not None

    task = {
        "schema_version": "2.1",
        "task_id": task_id,
        "case_id": case_id,
        "user_query": goal,
        "visible_context": {
            "intake_constraints": constraints,
            "proven": sketch["proven"],
            "unproven": sketch["unproven"],
            "planner_source": source,
        },
        "available_docs": [],
        "available_tools": tools,
        "safety_constraints": {
            "allow_write_operations": False,
            "require_evidence_for_dynamic_claims": True,
            "prohibited_operations": ["unauthorized_write", "bypass_permission"],
        },
        "business_constraints": {
            "human_fallback_available": True,
        },
        "metadata": {
            "source_dataset": "agent_intake",
            "source_ref": case_id,
            "platform_hint": None,
            "notes": "POC_VALIDATION_AGENT_INTAKE",
        },
        "created_at": now,
    }

    candidate_a = {
        "schema_version": "2.1",
        "candidate_id": "A",
        "task_id": task_id,
        "case_id": case_id,
        "name": "系统决策路径",
        "approach_type": "LIMITED_AGENT",
        "summary": "按已证明与未证明分列，只允许受控试运行档位，不把流程跑通外推为生产可用。",
        "model_provider": None,
        "model_name": None,
        "tools": tools,
        "assumptions": ["Evaluator 与 Decision Engine 独立于执行方"],
        "expected_strengths": ["fail-closed", "证据可复核"],
        "expected_risks": ["证据不足时不会给出上线结论"],
        "estimated": None,
        "metadata": {"source_dataset": "agent_intake", "source_ref": case_id, "platform_hint": None, "notes": "system_path"},
    }
    candidate_b = {
        **candidate_a,
        "candidate_id": "B",
        "name": "错误外推 Baseline",
        "approach_type": "OTHER",
        "summary": "看见实验跑通或质量达标就宣布可以上生产。这是对照反例，不是推荐方案。",
        "expected_strengths": ["叙事简单"],
        "expected_risks": ["结论外推", "把未知成本画成已测"],
        "metadata": {**candidate_a["metadata"], "notes": "naive_baseline"},
    }

    def spec_for(candidate_id: str) -> dict[str, Any]:
        return {
            "schema_version": "2.1",
            "experiment_id": f"exp-{candidate_id.lower()}-{suffix}",
            "task_id": task_id,
            "case_id": case_id,
            "candidate_id": candidate_id,
            "execution_mode": "FIXTURE",
            "objective": "验证该 POC 已证明项与未证明项，禁止外推为生产可用。",
            "success_criteria": {
                "min_quality_score": quality,
                "max_latency_ms": sketch["max_latency_ms"],
                "max_cost": sketch["max_cost"],
                "cost_currency": sketch["cost_currency"] or "CNY",
                "require_tool_trace": True,
                "require_evidence": True,
                "max_error_count": 0,
            },
            "required_tools": tools,
            "prohibited_tools": ["write_resource", "bypass_permission"],
            "simulation": {"profile": "NORMAL_SUCCESS" if candidate_id == "A" else "QUALITY_LOW", "seed": 20260918},
            "business_constraints": {"human_fallback_available": True},
            "repeats": 1,
            "created_at": now,
        }

    live_contract = {
        "contract_id": f"contract-{case_id}",
        "allowed_actions": ["ANSWER", "CLARIFY", "HANDOFF", "REFUSE"],
        "accepted_diagnoses": ["TASK_COMPLETED"],
        "required_tools": tools,
        "allowed_tools": tools,
        "forbidden_tools": ["write_resource", "bypass_permission"],
        "evidence_required": True,
        "should_escalate": False,
        "guardrail_required": False,
        "root_cause_must_be_evidenced": True,
        "required_response_keywords": [],
        "required_checks": {},
        "forbidden_claims": ["UNAUTHORIZED_ACTION"],
        "decision_criteria": {
            "source": "USER_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": quality},
            "cost": (
                {"status": "REQUIRED", "max_value": float(sketch["max_cost"]), "currency": sketch["cost_currency"] or "CNY"}
                if cost_applicable
                else {"status": "NOT_APPLICABLE", "max_value": None, "currency": None}
            ),
            "latency": (
                {"status": "REQUIRED", "max_ms": float(sketch["max_latency_ms"])}
                if latency_applicable
                else {"status": "NOT_APPLICABLE", "max_ms": None}
            ),
        },
        "evidence_requirements": {
            "required_types": [],
            "required_claim_ids": [],
            "required_targets": [case_id],
            "require_tool_link": True,
            "require_action_result": True,
        },
        "notes": "Agent intake frozen LIVE_POC contract. Cost/latency NOT_APPLICABLE unless user supplied numbers.",
    }

    return {
        "planner_source": source,
        "proven": sketch["proven"],
        "unproven": sketch["unproven"],
        "task": task,
        "candidates": [candidate_a, candidate_b],
        "experiment_specs": [spec_for("A"), spec_for("B")],
        "run_context": {
            "mode": "LIVE_POC",
            "live_acceptance_contract": live_contract,
        },
    }
