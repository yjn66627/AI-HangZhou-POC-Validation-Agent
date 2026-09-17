from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.yuanqi import YuanqiResponseAdapter, YuanqiResponseMapping
from executor_gateway.app import create_app
from executor_gateway.config import GatewaySettings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "executor_gateway" / "fixtures"

FAKE_APP_ID = "fake-assistant-id"
FAKE_APP_KEY = "fake-yuanqi-app-key"
FAKE_GATEWAY_KEY = "fake-gateway-api-key"
FAKE_URL = "https://yuanqi.example.invalid/openapi/v1/agent/chat/completions"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def settings() -> GatewaySettings:
    return GatewaySettings(
        assistant_id=FAKE_APP_ID,
        app_key=FAKE_APP_KEY,
        openapi_url=FAKE_URL,
        gateway_api_key=FAKE_GATEWAY_KEY,
        timeout_seconds=1.0,
    )


def headers(key: str = FAKE_GATEWAY_KEY):
    return {"Authorization": f"Bearer {key}"}


def request_payload():
    return load_json("backend_executor_request.json")


def success_response():
    payload = load_json("yuanqi_success_response.json")
    payload["assistant_id"] = FAKE_APP_ID
    return payload


def make_client(handler, *, provider=None):
    transport = httpx.MockTransport(handler)
    app = create_app(
        settings_provider=provider or settings,
        outbound_transport=transport,
    )
    return TestClient(app)


def mapping_adapter() -> YuanqiResponseAdapter:
    raw = json.loads((ROOT / "adapters" / "yuanqi_response_mapping_LIVE_GATEWAY.json").read_text(encoding="utf-8"))
    return YuanqiResponseAdapter(
        YuanqiResponseMapping(
            workflow_result_path=raw.get("workflow_result_path"),
            paths=dict(raw.get("paths") or {}),
            provider=str(raw.get("provider") or "Tencent Yuanqi"),
        )
    )


def test_health_ready_does_not_leak_config_values():
    client = make_client(lambda request: httpx.Response(500, request=request))
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    text = r.text
    assert FAKE_APP_KEY not in text
    assert FAKE_GATEWAY_KEY not in text
    assert FAKE_APP_ID not in text
    assert FAKE_URL not in text


def test_health_missing_config_fail_closed():
    from executor_gateway.config import GatewaySettings
    client = make_client(lambda request: httpx.Response(500, request=request), provider=lambda: GatewaySettings.from_environ({}))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["configured"] is False


def test_execute_missing_gateway_auth_is_401():
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload())
    assert r.status_code == 401


def test_execute_wrong_gateway_auth_is_401():
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload(), headers=headers("wrong-key"))
    assert r.status_code == 401


def test_execute_correct_gateway_auth_calls_upstream_and_returns_normalized():
    seen = {}
    def handler(request: httpx.Request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=success_response(), request=request)
    client = make_client(handler)
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert r.json()["meta"]["remote_execution_id"] == "yuanqi-response-001"
    assert seen["headers"]["authorization"] == f"Bearer {FAKE_APP_KEY}"


def test_internal_request_converts_to_expected_yuanqi_request_shape():
    seen = {}
    def handler(request: httpx.Request):
        seen.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=success_response(), request=request)
    client = make_client(handler)
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert seen["assistant_id"] == FAKE_APP_ID
    assert seen["user_id"] == "ai-poc-live-executor"
    assert seen["stream"] is False
    assert isinstance(seen["messages"], list) and seen["messages"]
    envelope = json.loads(seen["messages"][0]["content"][0]["text"])
    assert envelope["run_id"] == request_payload()["run_id"]
    assert envelope["task"] == request_payload()["task"]
    assert envelope["candidate"] == request_payload()["candidate"]
    assert envelope["experiment_spec"] == request_payload()["experiment_spec"]


def test_unicode_and_chinese_are_preserved_in_outbound_message():
    payload = request_payload()
    payload["task"]["user_query"] = '中文🙂 “引号”\n第二行\\escaped'
    seen = {}
    def handler(request: httpx.Request):
        seen.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=success_response(), request=request)
    client = make_client(handler)
    r = client.post("/execute", json=payload, headers=headers())
    assert r.status_code == 200
    envelope = json.loads(seen["messages"][0]["content"][0]["text"])
    assert envelope["task"]["user_query"] == payload["task"]["user_query"]


def test_appkey_not_in_response_or_logs(caplog):
    def handler(request: httpx.Request):
        return httpx.Response(200, json=success_response(), request=request)
    client = make_client(handler)
    with caplog.at_level("INFO", logger="executor_gateway.runtime"):
        r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    combined = r.text + "\n" + "\n".join(x.message for x in caplog.records)
    assert FAKE_APP_KEY not in combined
    assert FAKE_GATEWAY_KEY not in combined
    assert "Authorization" not in combined


@pytest.mark.parametrize("status", [400, 401, 403, 500, 502, 503])
def test_upstream_http_errors_never_become_success(status):
    client = make_client(lambda request: httpx.Response(status, json={"error": "fake"}, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    body = r.json()
    assert body["error"]["code"] == "UPSTREAM_HTTP_ERROR"
    assert body["error"]["upstream_status"] == status


def test_upstream_429_is_explicit_service_unavailable():
    client = make_client(lambda request: httpx.Response(429, json={"error": "rate"}, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "UPSTREAM_RATE_LIMITED"


def test_timeout_is_504():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("fake timeout", request=request)
    client = make_client(handler)
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_connection_failure_is_502():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("fake connect failure", request=request)
    client = make_client(handler)
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_CONNECTION_ERROR"


def test_non_json_response_is_502():
    client = make_client(lambda request: httpx.Response(200, text="not-json", request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_RESPONSE_INVALID"


def test_json_root_array_is_502():
    client = make_client(lambda request: httpx.Response(200, json=[1, 2], request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_RESPONSE_INVALID"


def test_choices_empty_is_502():
    payload = success_response(); payload["choices"] = []
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    assert "yuanqi_choices_empty" in r.json()["error"]["message"]


def test_invalid_agent_content_json_is_502():
    payload = success_response(); payload["choices"][0]["message"]["content"] = "{bad-json"
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 502
    assert "yuanqi_agent_content_invalid_json" in r.json()["error"]["message"]


def test_tool_fail_is_explicit_failed_execution_not_success():
    payload = load_json_fixture("yuanqi_tool_fail_response.json")
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert r.json()["execution"]["status"] == "FAILED"
    assert r.json()["execution"]["errors"][0]["code"] == "YUANQI_TOOL_FAIL"


def load_json_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sensitive_is_explicit_block_not_success():
    payload = load_json_fixture("yuanqi_sensitive_response.json")
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert r.json()["execution"]["status"] == "BLOCKED"
    assert r.json()["execution"]["output"]["final_action"] == "REFUSE"


def test_usage_mapping_is_preserved():
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.json()["execution"]["token_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "cache_hit_tokens": None,
        "cache_miss_tokens": None,
    }


def test_steps_and_tool_calls_mapping_is_preserved():
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    trace = r.json()["execution"]["tool_trace"]
    assert trace[0]["tool"] == "retrieve_context"
    assert trace[0]["tool_call_id"] == "call-real-1"
    assert trace[0]["latency_ms"] == 15
    assert trace[0]["result"]["matched"] == 2


def test_remote_execution_id_mapping_is_preserved():
    payload = success_response(); payload["id"] = "remote-runtime-id-123"
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.json()["meta"]["remote_execution_id"] == "remote-runtime-id-123"


def test_missing_cost_stays_not_provided_candidate_shape():
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.json()["execution"]["cost"] == {
        "currency": None, "total": None, "model": None, "tool": None, "other": None
    }


def test_missing_usage_is_not_fabricated():
    payload = success_response(); payload.pop("usage")
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert all(v is None for v in r.json()["execution"]["token_usage"].values())


def test_no_evidence_is_not_fabricated():
    payload = success_response()
    semantic = json.loads(payload["choices"][0]["message"]["content"])
    semantic["evidence"] = []
    semantic["root_cause_evidence_refs"] = []
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    client = make_client(lambda request: httpx.Response(200, json=payload, request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    assert r.json()["execution"]["evidence"] == []


def test_gateway_output_parses_with_frozen_yuanqi_response_adapter(success_bundle):
    client = make_client(lambda request: httpx.Response(200, json=success_response(), request=request))
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 200
    normalized = r.json()
    b = deepcopy(success_bundle)
    b["experiment_spec"]["execution_mode"] = "LIVE"
    b["experiment_spec"]["simulation"]["profile"] = None
    result = mapping_adapter().parse_with_context(
        normalized,
        task=b["task"],
        candidate=b["candidate"],
        experiment_spec=b["experiment_spec"],
        run_id="runtime-adapter-test",
        source_endpoint="http://127.0.0.1:8010/execute",
    )
    assert result["status"] == "SUCCESS"
    assert result["run_mode"] == "LIVE"
    assert result["provenance"]["remote_execution_id"] == "yuanqi-response-001"
    assert result["cost"]["total"]["availability"] == "NOT_PROVIDED"


def test_missing_config_execute_is_503_even_with_fake_auth():
    client = make_client(
        lambda request: httpx.Response(200, json=success_response(), request=request),
        provider=lambda: GatewaySettings.from_environ({}),
    )
    r = client.post("/execute", json=request_payload(), headers=headers())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "GATEWAY_NOT_CONFIGURED"


def test_env_loader_rejects_placeholder_values():
    env = {
        "YUANQI_APP_ID": "<PLACEHOLDER_ONLY>",
        "YUANQI_APP_KEY": "fake",
        "YUANQI_OPENAPI_URL": FAKE_URL,
        "EXECUTOR_GATEWAY_API_KEY": "fake",
    }
    from executor_gateway.config import GatewayConfigurationError
    with pytest.raises(GatewayConfigurationError, match="YUANQI_APP_ID"):
        GatewaySettings.from_environ(env)


def test_env_loader_accepts_fake_complete_config_without_network():
    env = {
        "YUANQI_APP_ID": "fake-aid",
        "YUANQI_APP_KEY": "fake-appkey",
        "YUANQI_OPENAPI_URL": "https://example.invalid/yuanqi",
        "EXECUTOR_GATEWAY_API_KEY": "fake-gateway",
        "YUANQI_HTTP_TIMEOUT_SECONDS": "3.5",
    }
    cfg = GatewaySettings.from_environ(env)
    assert cfg.assistant_id == "fake-aid"
    assert cfg.timeout_seconds == 3.5

