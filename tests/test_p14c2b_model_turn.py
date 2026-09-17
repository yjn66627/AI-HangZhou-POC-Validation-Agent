from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from executor_gateway.client import GatewayModerationBlocked, YuanqiOpenApiClient
from executor_gateway.compatibility import CompatibilityConfig, normalize_yuanqi_response
from executor_gateway.config import GatewaySettings
from executor_gateway.model_turn import ParseError, ParsedFinal, ParsedToolRequest, parse_model_turn


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "executor_gateway" / "fixtures"


def _valid_final() -> dict:
    payload = json.loads((FIXTURES / "yuanqi_success_response.json").read_text(encoding="utf-8"))
    return json.loads(payload["choices"][0]["message"]["content"])


def _tool_request(**updates) -> dict:
    value = {"turn_type": "TOOL_REQUEST", "requested_tool": "知识库测试结果", "arguments": {"query": "x"}}
    value.update(updates)
    return value


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def test_parse_legal_tool_request():
    parsed = parse_model_turn(_dump(_tool_request()))
    assert isinstance(parsed, ParsedToolRequest)
    assert parsed.request.requested_tool == "知识库测试结果"
    assert parsed.request.arguments == {"query": "x"}


def test_parse_legal_legacy_final_using_existing_authority():
    parsed = parse_model_turn(_dump(_valid_final()))
    assert isinstance(parsed, ParsedFinal)
    assert parsed.semantic["status"] == "SUCCESS"


def test_neither_branch_fails_closed():
    parsed = parse_model_turn('{"hello":"world"}')
    assert isinstance(parsed, ParseError)
    assert parsed.code == "MODEL_RESPONSE_UNION_NO_MATCH"


def test_union_ambiguity_fails_closed_when_both_validators_accept():
    permissive_final = Draft202012Validator({"type": "object"})
    parsed = parse_model_turn(_dump(_tool_request()), final_validator=permissive_final)
    assert isinstance(parsed, ParseError)
    assert parsed.code == "MODEL_RESPONSE_UNION_AMBIGUOUS"


def test_mixed_tool_request_and_final_fields_is_rejected():
    mixed = _tool_request(status="SUCCESS", final_action="ANSWER")
    parsed = parse_model_turn(_dump(mixed))
    assert isinstance(parsed, ParseError)


def test_tool_request_rejects_runtime_authority_fields():
    forbidden = [
        "tool_call_id",
        "request_sequence",
        "model_message_ref",
        "adapter_id",
        "executable_tool_id",
        "next_turn_mode",
        "run_id",
    ]
    for field in forbidden:
        parsed = parse_model_turn(_dump(_tool_request(**{field: "forbidden"})))
        assert isinstance(parsed, ParseError), field


def test_tool_request_extra_field_is_rejected():
    parsed = parse_model_turn(_dump(_tool_request(extra_junk=True)))
    assert isinstance(parsed, ParseError)


def test_strict_json_truncated_duplicate_nan_infinity_and_fence_rules_are_reused():
    bad_values = [
        '{"turn_type":"TOOL_REQUEST"',
        '{"turn_type":"TOOL_REQUEST","turn_type":"TOOL_REQUEST","requested_tool":"x","arguments":{}}',
        '{"turn_type":"TOOL_REQUEST","requested_tool":"x","arguments":{"x":NaN}}',
        '{"turn_type":"TOOL_REQUEST","requested_tool":"x","arguments":{"x":Infinity}}',
        _dump(_tool_request()) + " junk",
        _dump(_tool_request()) + _dump(_tool_request()),
    ]
    for raw in bad_values:
        parsed = parse_model_turn(raw)
        assert isinstance(parsed, ParseError), raw
        assert parsed.code == "MODEL_RESPONSE_STRICT_JSON_INVALID"

    fenced = "```json\n" + _dump(_tool_request()) + "\n```"
    assert isinstance(parse_model_turn(fenced), ParsedToolRequest)
    prose_fence = "result:\n" + fenced
    assert isinstance(parse_model_turn(prose_fence), ParseError)


def _settings() -> GatewaySettings:
    return GatewaySettings(
        assistant_id="fixture-assistant",
        app_key="fixture-app-key",
        openapi_url="https://yuanqi.example.invalid/openapi/v1/agent/chat/completions",
        gateway_api_key="fixture-gateway-key",
        timeout_seconds=1.0,
    )


def _platform_payload(content: str, *, finish_reason: str = "stop", native_steps=None, moderation_level=None) -> dict:
    choice = {
        "finish_reason": finish_reason,
        "message": {"role": "assistant", "content": content},
    }
    if native_steps is not None:
        choice["message"]["steps"] = native_steps
    if moderation_level is not None:
        choice["moderation_level"] = moderation_level
    return {
        "id": "mock-model-call-1",
        "assistant_id": "fixture-assistant",
        "created": 1,
        "choices": [choice],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_call_model_once_is_exactly_one_post_and_does_not_final_normalize_tool_request():
    calls = []
    payload = _platform_payload(_dump(_tool_request()))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        client.call_model_once(
            [{"role": "user", "content": [{"type": "text", "text": "offline"}]}],
            _settings(),
        )
    )
    assert len(calls) == 1
    assert result.finish_reason == "stop"
    assert json.loads(result.content)["turn_type"] == "TOOL_REQUEST"
    assert result.native_tool_trace_present is False


def test_call_model_once_detects_native_tool_trace_but_does_not_promote_it_to_authority():
    payload = _platform_payload(
        _dump(_tool_request()),
        native_steps=[{"role": "assistant", "tool_calls": [{"id": "native-1", "function": {"name": "x"}}]}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.native_tool_trace_present is True


def test_p0_native_nonempty_tool_calls_object_must_fail_closed():
    payload = _platform_payload(_dump(_valid_final()))
    payload["choices"][0]["message"]["tool_calls"] = {
        "id": "native-object-1",
        "function": {"name": "native_probe"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.native_tool_trace_present is True


@pytest.mark.parametrize(
    ("tool_calls_value", "expected"),
    [
        (None, False),
        ([], False),
        ([{"id": "native-list-1", "function": {"name": "native_probe"}}], True),
        ({"id": "native-object-1"}, True),
        ("native-tool-call", True),
        (1, True),
        (True, True),
    ],
)
def test_direct_message_tool_calls_fail_closed_matrix(tool_calls_value, expected):
    payload = _platform_payload(_dump(_valid_final()))
    payload["choices"][0]["message"]["tool_calls"] = tool_calls_value

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.native_tool_trace_present is expected


def test_direct_message_tool_calls_missing_is_known_empty():
    payload = _platform_payload(_dump(_valid_final()))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.native_tool_trace_present is False


def test_assistant_only_steps_without_tool_calls_remain_not_proven_native_trace():
    payload = _platform_payload(
        _dump(_valid_final()),
        native_steps=[{"role": "assistant", "content": "ordinary model step"}],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.native_tool_trace_present is False


def test_call_model_once_applies_same_moderation_authority_before_content_parse():
    payload = _platform_payload("WITHDRAWN_SECRET_BODY", moderation_level="2")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    try:
        asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    except GatewayModerationBlocked as exc:
        assert "yuanqi_moderation_level_content_withdrawn" in str(exc)
        assert "WITHDRAWN_SECRET_BODY" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("moderation block must fail closed")



@pytest.mark.parametrize("finish_reason", ["length", "tool_fail", "sensitive"])
def test_call_model_once_never_exposes_non_stop_content_for_branch_parsing(finish_reason):
    payload = _platform_payload("PARTIAL_OR_WITHDRAWN_CONTENT", finish_reason=finish_reason)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.call_model_once([{"role": "user", "content": []}], _settings()))
    assert result.finish_reason == finish_reason
    assert result.content is None

def test_legacy_execute_normalizer_semantics_remain_unchanged_for_success_fixture():
    payload = json.loads((FIXTURES / "yuanqi_success_response.json").read_text(encoding="utf-8"))
    payload["assistant_id"] = "fixture-assistant"
    expected = normalize_yuanqi_response(payload, CompatibilityConfig(assistant_id="fixture-assistant"))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload, request=request)

    request = json.loads((FIXTURES / "backend_executor_request.json").read_text(encoding="utf-8"))
    client = YuanqiOpenApiClient(transport=httpx.MockTransport(handler))
    actual = asyncio.run(client.execute(request, _settings()))
    assert len(calls) == 1
    assert actual.payload == expected
