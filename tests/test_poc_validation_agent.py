from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.agent.llm_client import (
    AgentLlmError,
    complete_chat_text,
    complete_intake_json,
    llm_configured,
    resolve_chat_completions_url,
)
from backend.agent.planner import classify_intent, compile_intake, is_small_talk
from backend.agent.service import plan_intake
from backend.app import RUN_STORE, app
from backend.schemas import RunRequest
from experiment.evaluation_contract import compile_live_acceptance

client = TestClient(app)


def _poll(url: str, headers: dict[str, str], timeout: float = 6.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"COMPLETED", "FAILED"}:
            return body
        time.sleep(0.01)
    raise AssertionError("run_not_finished")


def test_compile_intake_rejects_empty_goal():
    with pytest.raises(ValueError, match="goal_required"):
        compile_intake("  ")


def test_small_talk_does_not_enter_validation_pipeline():
    assert is_small_talk("你好")
    assert is_small_talk("你好呀！")
    assert classify_intent("谢谢") == "CHAT"
    assert classify_intent("我们想用大模型做客服，能不能上生产？") == "INTAKE"


def test_agent_hello_returns_chat_not_run(api_headers, monkeypatch):
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    RUN_STORE.clear()
    response = client.post(
        "/api/v1/agent/intake",
        json={"goal": "你好", "history": []},
        headers=api_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "SMALL_TALK"
    assert body["run_id"] is None
    assert body["reply"]
    assert RUN_STORE == {}


def test_chat_history_slice_allows_empty(monkeypatch):
    monkeypatch.setattr(
        "backend.agent.llm_client._post_chat",
        lambda messages, **kwargs: "你好，想验证哪个方案可以直接说。",
    )
    reply = complete_chat_text("你好", [])
    assert "上生产" not in reply


def test_resolve_deepseek_base_url_to_chat_completions():
    assert resolve_chat_completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert (
        resolve_chat_completions_url("https://api.deepseek.com/v1/chat/completions")
        == "https://api.deepseek.com/v1/chat/completions"
    )


def test_deepseek_without_api_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AGENT_LLM_MODEL", "deepseek-flash")
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    assert llm_configured() is False


def test_compile_intake_allows_production_question_and_keeps_cost_not_applicable(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    plan = plan_intake("客服大模型能不能上生产？还没测成本。", ["不允许写操作"])
    RunRequest.model_validate(
        {
            "task": plan["task"],
            "candidates": plan["candidates"],
            "experiment_specs": plan["experiment_specs"],
            "run_context": plan["run_context"],
        }
    )
    assert plan["planner_source"] == "DETERMINISTIC"
    assert plan["task"]["case_id"].startswith("INTAKE-")
    assert "上生产" in plan["task"]["user_query"]
    contract = compile_live_acceptance(plan["task"]["case_id"], plan["run_context"]["live_acceptance_contract"])
    assert contract["decision_criteria"]["source"] == "USER_CONFIRMED"
    assert contract["decision_criteria"]["cost"]["status"] == "NOT_APPLICABLE"
    assert contract["decision_criteria"]["latency"]["status"] == "NOT_APPLICABLE"
    assert contract["decision_criteria"]["quality"]["status"] == "REQUIRED"
    assert {row["candidate_id"] for row in plan["candidates"]} == {"A", "B"}
    assert plan["experiment_specs"][0]["execution_mode"] == "FIXTURE"


def test_compile_intake_reads_user_supplied_quality_and_cost(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    plan = compile_intake("做客服助手，质量门槛 0.9，成本 2 元，延迟 800 ms")
    criteria = plan["run_context"]["live_acceptance_contract"]["decision_criteria"]
    assert criteria["quality"]["min_score"] == 0.9
    assert criteria["cost"]["status"] == "REQUIRED"
    assert criteria["cost"]["max_value"] == 2.0
    assert criteria["latency"]["status"] == "REQUIRED"
    assert criteria["latency"]["max_ms"] == 800.0
    assert "真实货币成本" not in plan["unproven"]
    assert "延迟口径" not in plan["unproven"]


def test_llm_failure_falls_back_without_writing_decision(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_URL", "http://127.0.0.1:1/missing")

    def _boom(*_args, **_kwargs):
        raise AgentLlmError("agent_llm_call_failed")

    monkeypatch.setattr("backend.agent.planner.complete_intake_json", _boom)
    plan = compile_intake("知识库问答 POC")
    assert plan["planner_source"] == "DETERMINISTIC_FALLBACK"
    assert "decision" not in plan
    assert plan["run_context"]["mode"] == "LIVE_POC"


def test_llm_client_rejects_production_decision(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_URL", "http://llm.test/v1/chat/completions")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"choices": [{"message": {"content": json.dumps({"can_go_production": True, "proven": ["ok"]})}}]}

            return Response()

    monkeypatch.setattr("backend.agent.llm_client.httpx.Client", DummyClient)
    with pytest.raises(AgentLlmError, match="agent_llm_must_not_emit_decision"):
        complete_intake_json("能不能上生产", [])


def test_agent_intake_preview_does_not_enqueue(api_headers, monkeypatch):
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    RUN_STORE.clear()
    response = client.post(
        "/api/v1/agent/intake",
        json={"goal": "做客服助手，质量门槛 0.85", "submit": False},
        headers=api_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planner_source"] == "DETERMINISTIC"
    assert body["run_id"] is None
    assert "decision" not in body
    assert body["case_id"].startswith("INTAKE-")
    assert RUN_STORE == {}


def test_agent_intake_submits_into_existing_pipeline(api_headers, monkeypatch):
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    RUN_STORE.clear()
    created = client.post(
        "/api/v1/agent/intake",
        json={"goal": "我们想用大模型做客服，还没测成本。能不能上生产？", "constraints": ["不允许写操作"]},
        headers=api_headers,
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "QUEUED"
    assert body["run_id"]
    assert "decision" not in body
    summaries = {row["id"]: row["summary"] for row in body["candidates"]}
    assert "对照反例" in summaries["B"]
    got = _poll(body["result_url"], api_headers)
    assert got["status"] == "COMPLETED"
    assert got["run_context_mode"] == "LIVE_POC"
    assert got["evaluation_contract_source"] == "LIVE_ACCEPTANCE_CONTRACT"
    assert got["workflow_result"] is None
    assert got["decision_card"] is None
    assert len(got["candidate_results"]) == 2
    decisions = {
        row["candidate_id"]: row["repeats"][0]["decision_card"]["decision"]
        for row in got["candidate_results"]
    }
    assert set(decisions) == {"A", "B"}
    assert "PRODUCTION" not in json.dumps(decisions)
    assert got["comparison_result"]["recommended_candidate_id"] == "A"
