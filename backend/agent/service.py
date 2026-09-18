from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.schemas import RunRequest

from .llm_client import AgentLlmError, complete_chat_text, llm_configured
from .planner import classify_intent, compile_intake

_FALLBACK_CHAT = "你好，我是方案验证助手。想聊几句也可以；如果要判断一个方案能不能试运行，直接说说目标和限制就行。"


def handle_message(goal: str, constraints: list[str] | None = None, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    text = (goal or "").strip()
    if classify_intent(text) == "CHAT":
        return small_talk_public_view(text, history)
    return plan_intake(text, constraints)


def small_talk_public_view(goal: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    reply = _FALLBACK_CHAT
    source = "DETERMINISTIC"
    if llm_configured():
        try:
            reply = complete_chat_text(goal, history)
            source = "LLM"
        except AgentLlmError:
            source = "DETERMINISTIC_FALLBACK"
    return {
        "case_id": f"CHAT-{uuid4().hex[:8]}",
        "intent": "SMALL_TALK",
        "planner_source": source,
        "goal": goal.strip(),
        "reply": reply,
        "proven": [],
        "unproven": [],
        "candidates": [],
        "warnings": [],
    }


def is_small_talk_goal(goal: str) -> bool:
    return classify_intent(goal, allow_llm=False) == "CHAT"


def plan_intake(goal: str, constraints: list[str] | None = None) -> dict[str, Any]:
    plan = compile_intake(goal, constraints)
    RunRequest.model_validate(
        {
            "task": plan["task"],
            "candidates": plan["candidates"],
            "experiment_specs": plan["experiment_specs"],
            "run_context": plan["run_context"],
        }
    )
    return plan


def intake_public_view(plan: dict[str, Any]) -> dict[str, Any]:
    task = plan["task"]
    return {
        "case_id": task["case_id"],
        "intent": "VALIDATION",
        "planner_source": plan["planner_source"],
        "goal": task["user_query"],
        "reply": None,
        "proven": plan["proven"],
        "unproven": plan["unproven"],
        "candidates": [
            {"id": row["candidate_id"], "name": row["name"], "summary": row["summary"]}
            for row in plan["candidates"]
        ],
        "warnings": [],
    }
