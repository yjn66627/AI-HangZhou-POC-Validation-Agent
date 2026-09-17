from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app import RUN_STORE
from backend.yuanqi_transport_wrapper import YuanqiTransportWrapper, app as wrapper_app

ROOT = Path(__file__).resolve().parents[1]
WRAPPER_CLIENT = TestClient(wrapper_app)


def template_payload() -> dict:
    return json.loads((ROOT / "examples" / "yuanqi_front_half_payload_TEMPLATE_NOT_LIVE.json").read_text(encoding="utf-8"))


def envelope(payload: object) -> dict[str, str]:
    return {"payload_json": json.dumps(payload, ensure_ascii=False)}


def valid_headers(monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "transport-test-key")
    monkeypatch.setenv("EXECUTOR_MODE", "FIXTURE")
    return {"Authorization": "Bearer transport-test-key"}


def make_capture_app(status_code: int = 200) -> tuple[FastAPI, dict]:
    capture: dict = {}
    app = FastAPI()

    @app.post("/api/v1/yuanqi/runs")
    async def capture_route(request: Request):
        capture["body"] = await request.body()
        capture["json"] = await request.json()
        capture["authorization"] = request.headers.get("authorization")
        capture["content_length"] = request.headers.get("content-length")
        return JSONResponse({"received": capture["json"]}, status_code=status_code)

    return app, capture


def test_valid_payload_json_reaches_frozen_app(monkeypatch):
    RUN_STORE.clear()
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json=envelope(template_payload()), headers=valid_headers(monkeypatch))
    assert r.status_code == 202
    assert r.json()["status"] == "QUEUED"


def test_unicode_quotes_newlines_escapes_nested_and_candidate_order_are_lossless():
    payload = template_payload()
    payload["enterprise_requirement"]["description"] = '中文🙂 "引号"\n第二行\\路径'
    payload["enterprise_requirement"]["visible_context"] = {
        "nested": {"quote": 'A"B', "lines": ["甲\n乙", "\\escaped\\"]},
        "unicode": "杭州·超级智能体赛",
    }
    payload["candidates"] = [
        {**deepcopy(payload["candidates"][0]), "candidate_id": "cand-A", "name": "候选甲"},
        {**deepcopy(payload["candidates"][0]), "candidate_id": "cand-B", "name": "候选乙"},
        {**deepcopy(payload["candidates"][0]), "candidate_id": "cand-C", "name": "候选丙"},
    ]
    inner, capture = make_capture_app()
    client = TestClient(YuanqiTransportWrapper(inner))
    r = client.post(
        "/api/v1/yuanqi/runs",
        json=envelope(payload),
        headers={"Authorization": "Bearer preserved-header"},
    )
    assert r.status_code == 200
    assert capture["json"] == payload
    assert [x["candidate_id"] for x in capture["json"]["candidates"]] == ["cand-A", "cand-B", "cand-C"]
    assert capture["authorization"] == "Bearer preserved-header"
    assert int(capture["content_length"]) == len(capture["body"])


@pytest.mark.parametrize(
    ("payload_json", "error"),
    [
        ("{bad", "payload_json_malformed_json"),
        ("", "payload_json_must_not_be_empty"),
        ("   ", "payload_json_must_not_be_empty"),
        ("null", "payload_json_root_must_be_object"),
        ("[]", "payload_json_root_must_be_object"),
        ('"scalar"', "payload_json_root_must_be_object"),
        ("123", "payload_json_root_must_be_object"),
        ("true", "payload_json_root_must_be_object"),
    ],
)
def test_invalid_transport_payloads_are_rejected(payload_json, error):
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json={"payload_json": payload_json})
    assert r.status_code == 422
    assert error in r.json()["detail"]


@pytest.mark.parametrize("value", [None, {}, [], 7, False])
def test_payload_json_must_be_string(value):
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json={"payload_json": value})
    assert r.status_code == 422
    assert "payload_json_must_be_string" in r.json()["detail"]


def test_payload_json_with_outer_business_field_fails_closed():
    r = WRAPPER_CLIENT.post(
        "/api/v1/yuanqi/runs",
        json={"payload_json": json.dumps(template_payload()), "selected_candidate_id": "outer-override"},
    )
    assert r.status_code == 422
    assert "payload_json_conflicts_with_outer_fields" in r.json()["detail"]


@pytest.mark.parametrize("candidate_value", [None, []])
def test_existing_adapter_still_rejects_null_or_empty_candidates(monkeypatch, candidate_value):
    payload = template_payload()
    payload["candidates"] = candidate_value
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json=envelope(payload), headers=valid_headers(monkeypatch))
    assert r.status_code == 422
    assert "candidates_must_be_nonempty_list" in r.json()["detail"]


def test_existing_adapter_still_rejects_missing_required_structure(monkeypatch):
    payload = template_payload()
    payload.pop("enterprise_requirement")
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json=envelope(payload), headers=valid_headers(monkeypatch))
    assert r.status_code == 422
    assert "missing_source_path:enterprise_requirement" in r.json()["detail"]


def test_authorization_header_is_preserved_and_original_auth_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "correct-key")
    r = WRAPPER_CLIENT.post(
        "/api/v1/yuanqi/runs",
        json=envelope(template_payload()),
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid_api_key"


def test_original_auth_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "correct-key")
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json=envelope(template_payload()))
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_bearer_api_key"


def test_legacy_direct_object_path_still_works(monkeypatch):
    RUN_STORE.clear()
    r = WRAPPER_CLIENT.post("/api/v1/yuanqi/runs", json=template_payload(), headers=valid_headers(monkeypatch))
    assert r.status_code == 202
    assert r.json()["status"] == "QUEUED"


def test_health_is_untouched():
    r = WRAPPER_CLIENT.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "scope": "sandbox-or-local-mvp", "version": "1.2.3"}


def test_get_run_is_untouched(monkeypatch):
    headers = valid_headers(monkeypatch)
    r = WRAPPER_CLIENT.get("/api/v1/runs/not-present", headers=headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "run_not_found"


def test_wrapper_does_not_synthesize_success():
    inner, capture = make_capture_app(status_code=418)
    client = TestClient(YuanqiTransportWrapper(inner))
    r = client.post("/api/v1/yuanqi/runs", json=envelope({"nested": {"a": [1, 2, 3]}}))
    assert r.status_code == 418
    assert r.json()["received"] == {"nested": {"a": [1, 2, 3]}}
    assert capture["json"] == {"nested": {"a": [1, 2, 3]}}


def test_non_target_post_is_untouched():
    inner = FastAPI()

    @inner.post("/other")
    async def other(request: Request):
        return {"body": await request.json()}

    client = TestClient(YuanqiTransportWrapper(inner))
    body = {"payload_json": "this must remain a normal field on non-target route"}
    r = client.post("/other", json=body)
    assert r.status_code == 200
    assert r.json()["body"] == body
