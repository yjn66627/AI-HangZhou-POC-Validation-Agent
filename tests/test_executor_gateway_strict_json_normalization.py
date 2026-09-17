from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from executor_gateway.compatibility import (
    CompatibilityConfig,
    load_agent_contract_validator,
    normalize_yuanqi_response,
    parse_executor_agent_json_strict,
)

ROOT = Path(__file__).resolve().parents[1]
SUCCESS_FIXTURE = ROOT / "executor_gateway" / "fixtures" / "yuanqi_success_response.json"


def success_payload() -> dict:
    return json.loads(SUCCESS_FIXTURE.read_text(encoding="utf-8"))


def valid_semantic_text() -> str:
    return success_payload()["choices"][0]["message"]["content"]


def valid_semantic_object() -> dict:
    return json.loads(valid_semantic_text())


def validator():
    return load_agent_contract_validator()


def validate_contract(obj: dict) -> None:
    errors = list(validator().iter_errors(obj))
    assert errors == []


def test_pass_native_json_object():
    out = parse_executor_agent_json_strict(valid_semantic_text())
    validate_contract(out)


def test_pass_single_complete_json_fence_matching_real_preview_shape():
    raw = "```json\n" + valid_semantic_text() + "\n```"
    out = parse_executor_agent_json_strict(raw)
    validate_contract(out)


def test_pass_reasonable_outer_json_whitespace():
    raw = " \t\r\n" + valid_semantic_text() + "\r\n\t "
    out = parse_executor_agent_json_strict(raw)
    validate_contract(out)


def test_pass_json_fence_language_marker_is_case_insensitive():
    raw = "```JSON\n" + valid_semantic_text() + "\n```"
    out = parse_executor_agent_json_strict(raw)
    validate_contract(out)


def test_fail_prose_before_fence():
    raw = "以下是JSON：\n```json\n" + valid_semantic_text() + "\n```"
    with pytest.raises(ValueError, match="yuanqi_agent_content_outer_format_invalid"):
        parse_executor_agent_json_strict(raw)


def test_fail_explanation_after_fence():
    raw = "```json\n" + valid_semantic_text() + "\n```\n以上为结果。"
    with pytest.raises(ValueError, match="yuanqi_agent_content_outer_format_invalid"):
        parse_executor_agent_json_strict(raw)


def test_fail_two_code_fences():
    raw = (
        "```json\n" + valid_semantic_text() + "\n```\n"
        "```json\n" + valid_semantic_text() + "\n```"
    )
    with pytest.raises(ValueError):
        parse_executor_agent_json_strict(raw)


@pytest.mark.parametrize("lang", ["javascript", "python", "JSON5"])
def test_fail_other_language_fence(lang: str):
    raw = f"```{lang}\n{valid_semantic_text()}\n```"
    with pytest.raises(ValueError, match="yuanqi_agent_content_outer_format_invalid"):
        parse_executor_agent_json_strict(raw)


def test_fail_unlabelled_fence_not_supported():
    raw = "```\n" + valid_semantic_text() + "\n```"
    with pytest.raises(ValueError, match="yuanqi_agent_content_outer_format_invalid"):
        parse_executor_agent_json_strict(raw)


def test_fail_fenced_invalid_json_syntax():
    raw = "```json\n{\"status\": \"SUCCESS\",}\n```"
    with pytest.raises(ValueError, match="yuanqi_agent_content_invalid_json"):
        parse_executor_agent_json_strict(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '[{"status":"SUCCESS"}]',
        '"plain string"',
        "123",
        "null",
    ],
)
def test_fail_valid_json_non_object_roots(raw: str):
    with pytest.raises(ValueError, match="yuanqi_agent_content_root_must_be_object"):
        parse_executor_agent_json_strict(raw)


def test_fail_schema_missing_required_field():
    semantic = valid_semantic_object()
    semantic.pop("status")
    payload = success_payload()
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    with pytest.raises(ValueError, match="yuanqi_agent_content_contract_invalid"):
        normalize_yuanqi_response(payload, CompatibilityConfig(assistant_id="fixture-assistant"))


def test_fail_schema_additional_properties():
    semantic = valid_semantic_object()
    semantic["unexpected_extra"] = "forbidden"
    payload = success_payload()
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    with pytest.raises(ValueError, match="yuanqi_agent_content_contract_invalid"):
        normalize_yuanqi_response(payload, CompatibilityConfig(assistant_id="fixture-assistant"))


def test_fail_schema_enum_violation():
    semantic = valid_semantic_object()
    semantic["final_action"] = "DO_MAGIC"
    payload = success_payload()
    payload["choices"][0]["message"]["content"] = json.dumps(semantic, ensure_ascii=False)
    with pytest.raises(ValueError, match="yuanqi_agent_content_contract_invalid"):
        normalize_yuanqi_response(payload, CompatibilityConfig(assistant_id="fixture-assistant"))


def test_fail_long_text_containing_valid_json_object():
    raw = "diagnostic prefix\n" + valid_semantic_text() + "\ndiagnostic suffix"
    with pytest.raises(ValueError, match="yuanqi_agent_content_outer_format_invalid"):
        parse_executor_agent_json_strict(raw)


def test_fail_truncated_json_even_if_human_could_guess_completion():
    raw = valid_semantic_text()[:-1]
    with pytest.raises(ValueError, match="yuanqi_agent_content_invalid_json"):
        parse_executor_agent_json_strict(raw)


def test_gateway_response_normalization_accepts_fenced_semantic_content_without_payload_changes():
    payload = success_payload()
    original_semantic = json.loads(payload["choices"][0]["message"]["content"])
    payload["choices"][0]["message"]["content"] = (
        "```json\n"
        + json.dumps(original_semantic, ensure_ascii=False)
        + "\n```"
    )
    out = normalize_yuanqi_response(payload, CompatibilityConfig(assistant_id="fixture-assistant"))
    assert out["execution"]["status"] == original_semantic["status"]
    assert out["execution"]["output"]["final_action"] == original_semantic["final_action"]
    assert out["execution"]["quality_metrics"]["candidate_reported_score"] == original_semantic["candidate_reported_score"]
    assert out["execution"]["evidence"][0]["evidence_id"] == original_semantic["evidence"][0]["evidence_id"]


def test_normalizer_does_not_mutate_parsed_business_payload():
    semantic = valid_semantic_object()
    before = deepcopy(semantic)
    raw = "```json\n" + json.dumps(semantic, ensure_ascii=False, separators=(",", ":")) + "\n```"
    after = parse_executor_agent_json_strict(raw)
    assert after == before


def _runtime_settings():
    from executor_gateway.config import GatewaySettings

    return GatewaySettings(
        assistant_id="fixture-assistant",
        app_key="fixture-app-key",
        openapi_url="https://yuanqi.example.invalid/openapi/v1/agent/chat/completions",
        gateway_api_key="fixture-gateway-key",
        timeout_seconds=1.0,
    )


def _backend_request_payload() -> dict:
    path = ROOT / "executor_gateway" / "fixtures" / "backend_executor_request.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_gateway_execute_accepts_single_json_fence_via_mocktransport():
    import httpx
    from fastapi.testclient import TestClient
    from executor_gateway.app import create_app

    payload = success_payload()
    payload["assistant_id"] = "fixture-assistant"
    payload["choices"][0]["message"]["content"] = (
        "```json\n" + payload["choices"][0]["message"]["content"] + "\n```"
    )

    def handler(request: httpx.Request):
        return httpx.Response(200, json=payload, request=request)

    client = TestClient(create_app(settings_provider=_runtime_settings, outbound_transport=httpx.MockTransport(handler)))
    response = client.post(
        "/execute",
        json=_backend_request_payload(),
        headers={"Authorization": "Bearer fixture-gateway-key"},
    )
    assert response.status_code == 200
    assert response.json()["execution"]["status"] == "SUCCESS"


def test_gateway_execute_rejects_prose_plus_fence_via_mocktransport():
    import httpx
    from fastapi.testclient import TestClient
    from executor_gateway.app import create_app

    payload = success_payload()
    payload["assistant_id"] = "fixture-assistant"
    payload["choices"][0]["message"]["content"] = (
        "以下是JSON：\n```json\n" + payload["choices"][0]["message"]["content"] + "\n```"
    )

    def handler(request: httpx.Request):
        return httpx.Response(200, json=payload, request=request)

    client = TestClient(create_app(settings_provider=_runtime_settings, outbound_transport=httpx.MockTransport(handler)))
    response = client.post(
        "/execute",
        json=_backend_request_payload(),
        headers={"Authorization": "Bearer fixture-gateway-key"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_RESPONSE_INVALID"
    assert "yuanqi_agent_content_outer_format_invalid" in body["error"]["message"]


def _semantic_with_raw_check_token(token: str) -> str:
    semantic = valid_semantic_object()
    semantic["checks"] = {"strict_number_probe": "__RAW_TOKEN__"}
    raw = json.dumps(semantic, ensure_ascii=False, separators=(",", ":"))
    return raw.replace('"__RAW_TOKEN__"', token)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_fail_native_nonstandard_json_constants(token: str):
    raw = _semantic_with_raw_check_token(token)
    with pytest.raises(ValueError, match="yuanqi_agent_content_nonstandard_number"):
        parse_executor_agent_json_strict(raw)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_fail_fenced_nonstandard_json_constants(token: str):
    raw = "```json\n" + _semantic_with_raw_check_token(token) + "\n```"
    with pytest.raises(ValueError, match="yuanqi_agent_content_nonstandard_number"):
        parse_executor_agent_json_strict(raw)


@pytest.mark.parametrize("token", ["1e999", "-1e999"])
def test_fail_numeric_overflow_to_nonfinite(token: str):
    raw = _semantic_with_raw_check_token(token)
    with pytest.raises(ValueError, match="yuanqi_agent_content_nonfinite_number"):
        parse_executor_agent_json_strict(raw)


def test_fail_duplicate_key_at_top_level():
    raw = '{"status":"SUCCESS","status":"FAILED"}'
    with pytest.raises(ValueError, match="yuanqi_agent_content_duplicate_key:status"):
        parse_executor_agent_json_strict(raw)


def test_fail_duplicate_key_in_nested_object():
    raw = '{"checks":{"probe":1,"probe":2}}'
    with pytest.raises(ValueError, match="yuanqi_agent_content_duplicate_key:probe"):
        parse_executor_agent_json_strict(raw)
