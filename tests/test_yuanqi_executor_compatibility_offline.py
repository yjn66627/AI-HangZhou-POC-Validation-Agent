from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from backend.adapters.yuanqi import YuanqiResponseAdapter, YuanqiResponseMapping
from executor_gateway.compatibility import (
    CompatibilityConfig,
    build_yuanqi_api_request,
    load_agent_contract_validator,
    normalize_yuanqi_response,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "executor_gateway" / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def cfg(**kwargs) -> CompatibilityConfig:
    base = {
        "assistant_id": "<PLACEHOLDER_ASSISTANT_ID>",
        "user_id": "offline-test-user",
        "environment": "LOCAL",
    }
    base.update(kwargs)
    return CompatibilityConfig(**base)


def mapping_adapter() -> YuanqiResponseAdapter:
    raw = json.loads((ROOT / "adapters" / "yuanqi_response_mapping_LIVE_GATEWAY.json").read_text(encoding="utf-8"))
    return YuanqiResponseAdapter(
        YuanqiResponseMapping(
            workflow_result_path=raw.get("workflow_result_path"),
            paths=dict(raw["paths"]),
            provider=raw["provider"],
        )
    )


def test_build_request_known_fields_and_stream_false():
    built = build_yuanqi_api_request(load("backend_executor_request.json"), cfg())
    assert set(built) == {"assistant_id", "user_id", "stream", "messages"}
    assert built["assistant_id"] == "<PLACEHOLDER_ASSISTANT_ID>"
    assert built["stream"] is False
    envelope = json.loads(built["messages"][0]["content"][0]["text"])
    assert envelope == load("backend_executor_request.json")


def test_build_request_preserves_chinese_unicode_quotes_newlines_nested():
    req = load("backend_executor_request.json")
    req["task"]["visible_context"] = {
        "中文": "引号\"、换行\n、雪人☃",
        "nested": {"array": [1, {"x": "值"}]},
    }
    built = build_yuanqi_api_request(req, cfg())
    envelope = json.loads(built["messages"][0]["content"][0]["text"])
    assert envelope == req


def test_custom_variables_are_optional_string_map_only():
    built = build_yuanqi_api_request(load("backend_executor_request.json"), cfg(custom_variables={"trace_mode": "offline"}))
    assert built["custom_variables"] == {"trace_mode": "offline"}
    with pytest.raises(ValueError, match="custom_variables_must_be_string_map"):
        cfg(custom_variables={"bad": 1})  # type: ignore[arg-type]


def test_no_real_secret_or_environment_reading_api_exists():
    source = (ROOT / "executor_gateway" / "compatibility.py").read_text(encoding="utf-8")
    assert "os.getenv" not in source
    assert "os.environ" not in source
    assert "httpx.Client" not in source
    assert ".post(" not in source
    assert "requests." not in source


def test_mocktransport_success_response_can_be_normalized_without_network():
    expected_request = build_yuanqi_api_request(load("backend_executor_request.json"), cfg())
    payload = load("yuanqi_success_response.json")
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "mock.invalid"
        assert json.loads(request.content.decode("utf-8")) == expected_request
        return httpx.Response(200, json=payload)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = client.post("https://mock.invalid/openapi", json=expected_request)
    normalized = normalize_yuanqi_response(response.json(), cfg())
    assert normalized["meta"]["remote_execution_id"] == "yuanqi-response-001"
    assert normalized["execution"]["status"] == "SUCCESS"


def test_mocktransport_timeout_is_local_only():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("offline timeout", request=request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ReadTimeout):
        client.post("https://mock.invalid/openapi", json={"stream": False})


def test_mocktransport_non_json_response_is_not_silently_normalized():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="not-json")))
    response = client.post("https://mock.invalid/openapi", json={})
    with pytest.raises(json.JSONDecodeError):
        response.json()


def test_choices_empty_rejected():
    payload = load("yuanqi_success_response.json")
    payload["choices"] = []
    with pytest.raises(ValueError, match="yuanqi_choices_empty"):
        normalize_yuanqi_response(payload, cfg())


def test_message_content_malformed_json_rejected():
    payload = load("yuanqi_success_response.json")
    payload["choices"][0]["message"]["content"] = "{not-json"
    with pytest.raises(ValueError, match="yuanqi_agent_content_invalid_json"):
        normalize_yuanqi_response(payload, cfg())


def test_agent_contract_rejects_platform_metrics_in_content():
    payload = load("yuanqi_success_response.json")
    semantic = json.loads(payload["choices"][0]["message"]["content"])
    semantic["token_usage"] = {"total_tokens": 999}
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    with pytest.raises(ValueError, match="yuanqi_agent_content_contract_invalid"):
        normalize_yuanqi_response(payload, cfg())


def test_tool_fail_becomes_explicit_failure():
    out = normalize_yuanqi_response(load("yuanqi_tool_fail_response.json"), cfg())
    assert out["execution"]["status"] == "FAILED"
    assert out["execution"]["errors"][0]["code"] == "YUANQI_TOOL_FAIL"


def test_sensitive_becomes_explicit_block():
    out = normalize_yuanqi_response(load("yuanqi_sensitive_response.json"), cfg())
    assert out["execution"]["status"] == "BLOCKED"
    assert out["execution"]["output"]["final_action"] == "REFUSE"
    assert out["execution"]["output"]["guardrail_triggered"] is True


def test_usage_is_mapped_from_mock_usage_only():
    out = normalize_yuanqi_response(load("yuanqi_success_response.json"), cfg())
    assert out["execution"]["token_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "cache_hit_tokens": None,
        "cache_miss_tokens": None,
    }


def test_missing_usage_stays_not_provided_candidate_values():
    payload = load("yuanqi_success_response.json")
    payload.pop("usage")
    out = normalize_yuanqi_response(payload, cfg())
    assert all(v is None for v in out["execution"]["token_usage"].values())


def test_steps_tool_calls_and_time_cost_are_mapped():
    out = normalize_yuanqi_response(load("yuanqi_success_response.json"), cfg())
    trace = out["execution"]["tool_trace"]
    assert trace[0]["tool_call_id"] == "call-real-1"
    assert trace[0]["tool"] == "retrieve_context"
    assert trace[0]["arguments"] == {"query": "制度A"}
    assert trace[0]["result"]["matched"] == 2
    assert trace[0]["latency_ms"] == 15
    assert out["execution"]["latency"] == {"total_ms": 65, "model_ms": 50, "tool_ms": 15, "queue_ms": None}


def test_remote_execution_id_uses_mock_response_id():
    payload = load("yuanqi_success_response.json")
    payload["id"] = "mock-remote-id-xyz"
    out = normalize_yuanqi_response(payload, cfg())
    assert out["meta"]["remote_execution_id"] == "mock-remote-id-xyz"


def test_missing_remote_execution_id_rejected_not_invented():
    payload = load("yuanqi_success_response.json")
    payload.pop("id")
    with pytest.raises(ValueError, match="yuanqi_remote_execution_id_missing"):
        normalize_yuanqi_response(payload, cfg())


def test_cost_is_never_invented():
    out = normalize_yuanqi_response(load("yuanqi_success_response.json"), cfg())
    assert out["execution"]["cost"] == {"currency": None, "total": None, "model": None, "tool": None, "other": None}


def test_evidence_comes_only_from_real_mock_tool_result():
    out = normalize_yuanqi_response(load("yuanqi_success_response.json"), cfg())
    evidence = out["execution"]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["source_ref"] == "call-real-1"
    assert evidence[0]["action"] == "retrieve_context"
    assert "matched" in evidence[0]["content"]
    assert out["execution"]["tool_trace"][0]["evidence_refs"] == ["ev-real-1"]


def test_no_evidence_is_not_fabricated_even_when_tool_trace_exists():
    payload = load("yuanqi_success_response.json")
    semantic = json.loads(payload["choices"][0]["message"]["content"])
    semantic["evidence"] = []
    semantic["root_cause_evidence_refs"] = []
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    out = normalize_yuanqi_response(payload, cfg())
    assert out["execution"]["tool_trace"]
    assert out["execution"]["evidence"] == []
    assert out["execution"]["tool_trace"][0]["evidence_refs"] == []


def test_fake_evidence_reference_rejected():
    payload = load("yuanqi_success_response.json")
    semantic = json.loads(payload["choices"][0]["message"]["content"])
    semantic["evidence"][0]["source_ref"] = "not-a-real-tool-call"
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    with pytest.raises(ValueError, match="evidence_source_ref_not_real_tool_result"):
        normalize_yuanqi_response(payload, cfg())


def test_explicit_tool_name_map_only_maps_confirmed_ids():
    payload = load("yuanqi_success_response.json")
    payload["choices"][0]["message"]["steps"][0]["tool_calls"][0]["function"]["name"] = "opaque-id"
    out = normalize_yuanqi_response(payload, cfg(tool_name_map={"opaque-id": "retrieve_context"}))
    assert out["execution"]["tool_trace"][0]["tool"] == "retrieve_context"


def test_gateway_mapping_candidate_is_parseable_by_frozen_adapter(success_bundle):
    normalized = normalize_yuanqi_response(load("yuanqi_success_response.json"), cfg())
    adapter = mapping_adapter()
    b = deepcopy(success_bundle)
    b["experiment_spec"]["execution_mode"] = "LIVE"
    b["experiment_spec"]["simulation"]["profile"] = None
    result = adapter.parse_with_context(
        normalized,
        task=b["task"],
        candidate=b["candidate"],
        experiment_spec=b["experiment_spec"],
        run_id="offline-adapter-run",
        source_endpoint="offline://compatibility-adapter",
    )
    assert result["run_mode"] == "LIVE"
    assert result["status"] == "SUCCESS"
    assert result["provenance"]["remote_execution_id"] == "yuanqi-response-001"
    assert result["token_usage"]["total_tokens"]["value"] == 18
    assert result["cost"]["total"]["availability"] == "NOT_PROVIDED"


def test_normalized_failure_can_become_valid_failed_workflow_result(success_bundle):
    normalized = normalize_yuanqi_response(load("yuanqi_tool_fail_response.json"), cfg())
    adapter = mapping_adapter()
    b = deepcopy(success_bundle)
    b["experiment_spec"]["execution_mode"] = "LIVE"
    b["experiment_spec"]["simulation"]["profile"] = None
    result = adapter.parse_with_context(
        normalized,
        task=b["task"], candidate=b["candidate"], experiment_spec=b["experiment_spec"],
        run_id="offline-tool-fail", source_endpoint="offline://compatibility-adapter",
    )
    assert result["status"] == "FAILED"
    assert result["errors"][0]["code"] == "YUANQI_TOOL_FAIL"


def test_existing_template_mapping_is_not_overwritten():
    assert (ROOT / "adapters" / "yuanqi_response_mapping_TEMPLATE_NOT_LIVE_VERIFIED.json").exists()
    new = json.loads((ROOT / "adapters" / "yuanqi_response_mapping_LIVE_GATEWAY.json").read_text(encoding="utf-8"))
    assert new["status"] == "GATEWAY_RUNTIME_OFFLINE_PASS_NOT_LIVE_VERIFIED"


def test_env_example_contains_only_placeholders():
    text = (ROOT / "executor_gateway" / ".env.example").read_text(encoding="utf-8")
    assert "YUANQI_APP_ID=" in text
    assert "YUANQI_APP_KEY=" in text
    assert "YUANQI_OPENAPI_URL=" in text
    assert "EXECUTOR_GATEWAY_API_KEY=" in text
    assert "<PLACEHOLDER_ONLY>" not in text
    assert "sk-" not in text
    assert "Bearer " not in text


def test_agent_contract_schema_is_valid():
    validator = load_agent_contract_validator()
    assert validator is not None
