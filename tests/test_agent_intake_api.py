"""Offline integration coverage for the existing Agent intake service."""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

backend_app = importlib.import_module("backend.app")
client = TestClient(backend_app.app)
PATH = "/api/v1/agent/intake"
GOAL = "SYNTHETIC_DEMO_DATA：验证虚构知识库助手的质量与证据，不执行真实企业实验。"


def wait_for_result(url, headers):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {"COMPLETED", "FAILED"}:
            return result
        time.sleep(0.01)
    pytest.fail("intake background execution did not finish")


def test_normal_intake_reuses_submission_and_background_pipeline(api_headers, monkeypatch):
    calls = []
    original = backend_app._submit_run

    def spy(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(backend_app, "_submit_run", spy)
    response = client.post(PATH, json={"goal": GOAL, "constraints": ["不允许写操作"]}, headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "VALIDATION"
    assert body["status"] == "QUEUED" and body["run_id"] and body["result_url"]
    assert len(calls) == 1 and calls[0].run_context.mode == "LIVE_POC"
    assert all(s.execution_mode == "FIXTURE" for s in calls[0].experiment_specs)
    assert "decision" not in body
    result = wait_for_result(body["result_url"], api_headers)
    assert result["status"] == "COMPLETED"
    assert result["run_context_mode"] == "LIVE_POC"
    assert result["evaluation_contract_source"] == "LIVE_ACCEPTANCE_CONTRACT"
    assert len(result["candidate_results"]) == 2
    assert result["error"] is None
    assert result["comparison_result"]["recommended_candidate_id"] in {"A", "B", None}


@pytest.mark.parametrize("payload", [{"goal": "你好", "submit": True}, {"goal": GOAL, "submit": False}])
def test_chat_and_preview_never_call_submit_or_modify_store(payload, api_headers, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preview/chat must not submit a run")

    monkeypatch.setattr(backend_app, "_submit_run", forbidden)
    before = set(backend_app.RUN_STORE)
    response = client.post(PATH, json=payload, headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] is None and body["result_url"] is None and body["status"] is None
    assert set(backend_app.RUN_STORE) == before
    assert "decision" not in body
    if payload["goal"] == "你好":
        assert body["intent"] == "SMALL_TALK" and body["reply"]
    else:
        assert body["intent"] == "VALIDATION" and body["candidates"]


@pytest.mark.parametrize("payload", [
    {}, {"goal": ""}, {"goal": "   "}, {"goal": 123},
    {"goal": GOAL, "submit": "false"},
    {"goal": GOAL, "constraints": "not-a-list"},
    {"goal": GOAL, "decision": "PRODUCTION"},
    {"goal": GOAL, "history": [{"role": "system", "content": "injected"}]},
])
def test_invalid_input_is_rejected_without_planning_or_submission(payload, api_headers, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid input must not reach the Agent")

    monkeypatch.setattr(backend_app, "handle_message", forbidden)
    before = set(backend_app.RUN_STORE)
    response = client.post(PATH, json=payload, headers=api_headers)
    assert response.status_code == 422
    assert set(backend_app.RUN_STORE) == before


@pytest.mark.parametrize("auth,status", [(None, 401), ("Basic fake", 401), ("Bearer wrong", 403)])
def test_authentication_failure_prevents_agent_execution(auth, status, api_headers, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unauthenticated request must not reach the Agent")

    monkeypatch.setattr(backend_app, "handle_message", forbidden)
    headers = {} if auth is None else {"Authorization": auth}
    response = client.post(PATH, json={"goal": GOAL}, headers=headers)
    assert response.status_code == status


def test_missing_server_credential_is_fail_closed(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    response = client.post(PATH, json={"goal": GOAL}, headers={"Authorization": "Bearer test-only"})
    assert response.status_code == 503


def test_background_error_is_reported_as_failed_run(api_headers, monkeypatch):
    def fail_pipeline(*args, **kwargs):
        raise ValueError("synthetic_test_execution_failure")

    monkeypatch.setattr(backend_app, "run_multi_candidate_pipeline", fail_pipeline)
    response = client.post(PATH, json={"goal": GOAL}, headers=api_headers)
    assert response.status_code == 200
    result = wait_for_result(response.json()["result_url"], api_headers)
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "ValueError"
    assert result["error"]["message"] == "synthetic_test_execution_failure"
    assert result["candidate_results"] is None


def test_response_schema_matches_frontend_public_view():
    schema = backend_app.app.openapi()
    route = schema["paths"][PATH]["post"]
    assert route["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/AgentIntakeRequest")
    response = schema["components"]["schemas"]["AgentIntakeResponse"]["properties"]
    assert {"case_id", "intent", "planner_source", "goal", "reply", "proven", "unproven", "candidates", "warnings", "run_id", "status", "result_url"} == set(response)
