"""Minimal Python CloudBase HTTP-function candidate.

This module intentionally implements only the Tool path required by the
frozen V1.0 contract.  It uses a packaged read-only fixture and the runtime
environment variable ``ISOLATED_CLOUD_TEST_CREDENTIAL`` for Bearer auth.
There is no RUN_STORE, network client, retry loop, framework, or process-local
business state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Mapping, Optional
from urllib.parse import parse_qs


TOOL_PATH = "/tool/project_experiment_run_read"
TOOL_NAME = "实验运行结果读取"
TOOL_SOURCE = "PROJECT_BACKEND_RUN_STORE"
AUTH_ENV_NAME = "ISOLATED_CLOUD_TEST_CREDENTIAL"
FIXTURE_MODE = "READ_ONLY_PRELOADED_FIXTURE"
INTERNAL_METHOD = "GET"
INTERNAL_RETRY_COUNT = 0
SERVER_SIDE_BINDING = True
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "synthetic_demo_success.json"
EXPECTED_FIXTURE_KEYS = {
    "resource_kind",
    "status",
    "output",
    "quality_metrics",
    "latency",
    "cost",
    "token_usage",
    "errors",
}


def _json_response(status_code: int, payload: Mapping[str, Any], *, allow: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if allow:
        headers["Allow"] = allow
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def _event_value(event: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = event.get(key)
        if value is not None:
            return value
    return None


def _request_method(event: Mapping[str, Any]) -> str:
    request = event.get("request")
    if isinstance(request, Mapping):
        value = _event_value(request, "httpMethod", "method")
        if value:
            return str(value).upper()
    value = _event_value(event, "httpMethod", "method")
    return str(value or "GET").upper()


def _request_path(event: Mapping[str, Any]) -> str:
    request = event.get("request")
    if isinstance(request, Mapping):
        value = _event_value(request, "path", "rawPath")
        if value:
            return str(value).split("?", 1)[0]
    value = _event_value(event, "path", "rawPath")
    return str(value or "").split("?", 1)[0]


def _headers(event: Mapping[str, Any]) -> Dict[str, Any]:
    raw = event.get("headers")
    if not isinstance(raw, Mapping):
        request = event.get("request")
        raw = request.get("headers") if isinstance(request, Mapping) else {}
    return {str(key).lower(): value for key, value in raw.items()}


def _has_query_parameters(event: Mapping[str, Any]) -> bool:
    query = event.get("queryStringParameters")
    if isinstance(query, Mapping) and len(query) > 0:
        return True
    multi_query = event.get("multiValueQueryStringParameters")
    if isinstance(multi_query, Mapping) and len(multi_query) > 0:
        return True
    raw_query = event.get("rawQueryString")
    if isinstance(raw_query, str) and parse_qs(raw_query, keep_blank_values=True):
        return True
    path = str(_event_value(event, "path", "rawPath") or "")
    return "?" in path and bool(parse_qs(path.split("?", 1)[1], keep_blank_values=True))


def _valid_bearer(event: Mapping[str, Any]) -> bool:
    expected = os.environ.get(AUTH_ENV_NAME, "")
    supplied = _headers(event).get("authorization")
    return bool(expected and isinstance(supplied, str) and supplied == "Bearer " + expected)


def _load_fixture() -> Dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or set(raw) != EXPECTED_FIXTURE_KEYS:
        raise ValueError("readonly fixture does not match the projected Tool schema")
    if raw.get("resource_kind") != "EXPERIMENT_RUN_RESULT_SNAPSHOT":
        raise ValueError("readonly fixture resource_kind is invalid")
    if raw.get("status") != "SUCCESS":
        raise ValueError("readonly fixture is not the candidate success fixture")
    return raw


def _tool_success(data: Dict[str, Any], started: float) -> Dict[str, Any]:
    return {
        "status": "SUCCESS",
        "tool": TOOL_NAME,
        "arguments": {},
        "data": data,
        "error": None,
        "latency_ms": max(0, int((perf_counter() - started) * 1000)),
        "source": TOOL_SOURCE,
    }


def _tool_error(exc: Exception) -> Dict[str, Any]:
    return {
        "status": "ERROR",
        "tool": TOOL_NAME,
        "arguments": {},
        "data": None,
        "error": {"code": "FIXTURE_LOAD_ERROR", "message": str(exc)},
        "latency_ms": 0,
        "source": TOOL_SOURCE,
    }


def main(event: Optional[Mapping[str, Any]], context: Any = None) -> Dict[str, Any]:
    """CloudBase Python function entrypoint using API Gateway-style events."""

    del context
    request = event if isinstance(event, Mapping) else {}
    if _request_path(request) != TOOL_PATH:
        return _json_response(404, {"detail": "Not Found"})
    if _request_method(request) != "GET":
        return _json_response(405, {"detail": "Method Not Allowed"}, allow="GET")
    if not _valid_bearer(request):
        return _json_response(401, {"detail": "invalid_task_owned_test_credential"})
    if _has_query_parameters(request):
        return _json_response(400, {"detail": "zero_parameter_contract_requires_empty_query"})

    started = perf_counter()
    try:
        return _json_response(200, _tool_success(_load_fixture(), started))
    except Exception as exc:
        return _json_response(200, _tool_error(exc))


handler = main
