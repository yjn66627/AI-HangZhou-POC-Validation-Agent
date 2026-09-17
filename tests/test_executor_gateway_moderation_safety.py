from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import executor_gateway.compatibility as compatibility
from executor_gateway.app import create_app
from executor_gateway.compatibility import CompatibilityConfig, normalize_yuanqi_response
from executor_gateway.config import GatewaySettings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "executor_gateway" / "fixtures"

FAKE_APP_ID = "fake-assistant-id"
FAKE_APP_KEY = "fake-yuanqi-app-key"
FAKE_GATEWAY_KEY = "fake-gateway-api-key"
FAKE_URL = "https://yuanqi.example.invalid/openapi/v1/agent/chat/completions"
WITHDRAWN_MARKER = "WITHDRAWN_BODY_MUST_NOT_LEAK"


def load_json_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def cfg() -> CompatibilityConfig:
    return CompatibilityConfig(assistant_id=FAKE_APP_ID)


def success_payload() -> dict:
    payload = load_json_fixture("yuanqi_success_response.json")
    payload["assistant_id"] = FAKE_APP_ID
    return payload


def set_valid_business_content_marker(payload: dict, marker: str = WITHDRAWN_MARKER) -> None:
    semantic = json.loads(payload["choices"][0]["message"]["content"])
    semantic["response"] = marker
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)


def settings() -> GatewaySettings:
    return GatewaySettings(
        assistant_id=FAKE_APP_ID,
        app_key=FAKE_APP_KEY,
        openapi_url=FAKE_URL,
        gateway_api_key=FAKE_GATEWAY_KEY,
        timeout_seconds=1.0,
    )


def request_payload() -> dict:
    return load_json_fixture("backend_executor_request.json")


def gateway_client(upstream_payload: dict) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=upstream_payload, request=request)

    return TestClient(
        create_app(
            settings_provider=settings,
            outbound_transport=httpx.MockTransport(handler),
        )
    )


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {FAKE_GATEWAY_KEY}"}


def test_stop_without_moderation_remains_normal_success_path():
    out = normalize_yuanqi_response(success_payload(), cfg())
    assert out["execution"]["status"] == "SUCCESS"
    assert out["execution"]["output"]["final_action"] == "ANSWER"


@pytest.mark.parametrize("moderation_level", [None, "", "   "])
def test_stop_with_null_or_blank_moderation_keeps_existing_normal_path(moderation_level):
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = moderation_level
    out = normalize_yuanqi_response(payload, cfg())
    assert out["execution"]["status"] == "SUCCESS"


def test_moderation_level_2_fails_before_business_content_normalizer(monkeypatch):
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = "2"
    set_valid_business_content_marker(payload)

    def must_not_run(*args, **kwargs):  # pragma: no cover - execution itself is failure
        raise AssertionError("business content normalizer must not run")

    monkeypatch.setattr(compatibility, "_semantic_from_content", must_not_run)
    with pytest.raises(ValueError, match="yuanqi_moderation_level_content_withdrawn") as exc:
        normalize_yuanqi_response(payload, cfg())
    assert WITHDRAWN_MARKER not in str(exc.value)


def test_moderation_level_1_fails_before_business_content_normalizer(monkeypatch):
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = "1"
    set_valid_business_content_marker(payload)

    def must_not_run(*args, **kwargs):  # pragma: no cover - execution itself is failure
        raise AssertionError("business content normalizer must not run")

    monkeypatch.setattr(compatibility, "_semantic_from_content", must_not_run)
    with pytest.raises(ValueError, match="yuanqi_moderation_level_session_end") as exc:
        normalize_yuanqi_response(payload, cfg())
    assert WITHDRAWN_MARKER not in str(exc.value)


def test_unknown_nonempty_moderation_level_fails_closed():
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = "future_value"
    set_valid_business_content_marker(payload)
    with pytest.raises(ValueError, match="yuanqi_moderation_level_unsupported") as exc:
        normalize_yuanqi_response(payload, cfg())
    assert WITHDRAWN_MARKER not in str(exc.value)


@pytest.mark.parametrize("bad_value", [2, 1, True, [], {}])
def test_moderation_level_type_anomaly_fails_closed(bad_value):
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = bad_value
    with pytest.raises(ValueError, match="yuanqi_moderation_level_invalid_type"):
        normalize_yuanqi_response(payload, cfg())


def test_sensitive_finish_reason_still_fails_closed_without_consuming_content():
    payload = success_payload()
    payload["choices"][0]["finish_reason"] = "sensitive"
    payload["choices"][0]["message"]["content"] = WITHDRAWN_MARKER
    out = normalize_yuanqi_response(payload, cfg())
    assert out["execution"]["status"] == "BLOCKED"
    assert out["execution"]["output"]["final_action"] == "REFUSE"
    assert WITHDRAWN_MARKER not in json.dumps(out, ensure_ascii=False)


def test_tool_fail_finish_reason_still_fails_closed_without_consuming_content():
    payload = success_payload()
    payload["choices"][0]["finish_reason"] = "tool_fail"
    payload["choices"][0]["message"]["content"] = WITHDRAWN_MARKER
    out = normalize_yuanqi_response(payload, cfg())
    assert out["execution"]["status"] == "FAILED"
    assert out["execution"]["errors"][0]["code"] == "YUANQI_TOOL_FAIL"
    assert WITHDRAWN_MARKER not in json.dumps(out, ensure_ascii=False)


def test_gateway_moderation_level_2_returns_existing_protocol_error_without_body_or_secret_leak(caplog):
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = "2"
    set_valid_business_content_marker(payload)
    client = gateway_client(payload)

    with caplog.at_level("WARNING", logger="executor_gateway.runtime"):
        response = client.post("/execute", json=request_payload(), headers=auth_headers())

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_RESPONSE_INVALID"
    assert "yuanqi_moderation_level_content_withdrawn" in body["error"]["message"]
    combined = response.text + "\n" + "\n".join(record.message for record in caplog.records)
    assert WITHDRAWN_MARKER not in combined
    assert FAKE_APP_KEY not in combined
    assert FAKE_GATEWAY_KEY not in combined


def test_gateway_unknown_moderation_level_returns_existing_protocol_error():
    payload = success_payload()
    payload["choices"][0]["moderation_level"] = "3"
    client = gateway_client(payload)
    response = client.post("/execute", json=request_payload(), headers=auth_headers())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_RESPONSE_INVALID"
    assert "yuanqi_moderation_level_unsupported" in response.json()["error"]["message"]
