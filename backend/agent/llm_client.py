from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .prompt import CHAT_SYSTEM_PROMPT, INTAKE_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT


class AgentLlmError(RuntimeError):
    pass


def _llm_api_key() -> str:
    return (os.getenv("AGENT_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "").strip()


def resolve_chat_completions_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        raise AgentLlmError("agent_llm_url_not_configured")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def llm_configured() -> bool:
    url = os.getenv("AGENT_LLM_URL", "").strip()
    if not url:
        return False
    if "deepseek.com" in url.lower() and not _llm_api_key():
        return False
    return True


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AgentLlmError("agent_llm_output_not_json")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AgentLlmError("agent_llm_output_not_json") from exc
    if not isinstance(parsed, dict):
        raise AgentLlmError("agent_llm_output_not_object")
    return parsed


def _chat_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = _llm_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _post_chat(messages: list[dict[str, str]], *, json_object: bool, temperature: float) -> str:
    raw_url = os.getenv("AGENT_LLM_URL", "").strip()
    url = resolve_chat_completions_url(raw_url)
    model = os.getenv("AGENT_LLM_MODEL", "deepseek-flash").strip() or "deepseek-flash"
    timeout = float(os.getenv("AGENT_LLM_TIMEOUT_SECONDS", "30"))
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "stream": False,
        "messages": messages,
    }
    if "deepseek.com" in url.lower():
        payload["thinking"] = {"type": "disabled"}
        if json_object:
            payload["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=_chat_headers(), json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AgentLlmError(f"agent_llm_call_failed:{exc}") from exc
    content = (
        body.get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(body, dict)
        else None
    )
    if not isinstance(content, str) or not content.strip():
        raise AgentLlmError("agent_llm_empty_content")
    return content


def classify_intent_llm(message: str) -> str:
    raw = _post_chat(
        [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        json_object=True,
        temperature=0,
    )
    parsed = _parse_json_content(raw)
    intent = str(parsed.get("intent") or "").strip().upper()
    if intent in {"CHAT", "SMALL_TALK"}:
        return "CHAT"
    if intent == "INTAKE":
        return "INTAKE"
    raise AgentLlmError("agent_llm_intent_invalid")


def complete_chat_text(message: str, history: list[dict[str, str]] | None = None) -> str:
    messages: list[dict[str, str]] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for row in (history or [])[-8:]:
        role = str(row.get("role") or "")
        content = str(row.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    reply = _post_chat(messages, json_object=False, temperature=0.6).strip()
    if any(phrase in reply for phrase in ("可以上生产", "生产可用", "成本可控", "Production Ready")):
        raise AgentLlmError("agent_llm_must_not_claim_production")
    return reply


def complete_intake_json(goal: str, constraints: list[str]) -> dict[str, Any]:
    raw_url = os.getenv("AGENT_LLM_URL", "").strip()
    if not raw_url:
        raise AgentLlmError("agent_llm_url_not_configured")
    content = _post_chat(
        [
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"goal": goal, "constraints": constraints}, ensure_ascii=False),
            },
        ],
        json_object=True,
        temperature=0,
    )
    parsed = _parse_json_content(content)
    if parsed.get("can_go_production") is True or parsed.get("decision"):
        raise AgentLlmError("agent_llm_must_not_emit_decision")
    return parsed
