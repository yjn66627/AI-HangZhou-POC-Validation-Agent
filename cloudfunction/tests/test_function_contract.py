"""Public contract tests: synthetic response data, no cloud requests."""

from __future__ import annotations

import copy
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "function" / "index.py"
spec = importlib.util.spec_from_file_location("public_cloudfunction_index", FUNCTION)
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)

# An intentionally public unit-test placeholder; never used by a live service.
AUTH_VALUE = "public-unit-test-placeholder"


def event(path=index.TOOL_PATH, method="GET", auth=None, query=None):
    value = {"path": path, "httpMethod": method, "headers": {}, "body": None}
    if auth is not None:
        value["headers"]["Authorization"] = auth
    if query is not None:
        value["queryStringParameters"] = query
    return value


def body(response):
    return json.loads(response["body"])


def deep_equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return list(left) == list(right) and all(deep_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(deep_equal(a, b) for a, b in zip(left, right))
    return left == right


class FunctionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(index.FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "contract/TOOL_RESPONSE_DEEP_SCHEMA.json").read_text(encoding="utf-8"))
        cls.contract = json.loads((ROOT / "contract/TOOL_CONTRACT_V1.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def setUp(self):
        self.old_auth = os.environ.get(index.AUTH_ENV_NAME)
        os.environ[index.AUTH_ENV_NAME] = AUTH_VALUE

    def tearDown(self):
        if self.old_auth is None:
            os.environ.pop(index.AUTH_ENV_NAME, None)
        else:
            os.environ[index.AUTH_ENV_NAME] = self.old_auth

    def test_success_envelope_and_data_are_exact(self):
        response = index.main(event(auth="Bearer " + AUTH_VALUE))
        self.assertEqual(response["statusCode"], 200)
        payload = body(response)
        self.assertEqual(set(payload), {"status", "tool", "arguments", "data", "error", "latency_ms", "source"})
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertEqual(payload["tool"], self.contract["success_payload"]["properties"]["tool"]["const"])
        self.assertEqual(payload["arguments"], {})
        self.assertIsNone(payload["error"])
        self.assertIsInstance(payload["latency_ms"], int)
        self.assertGreaterEqual(payload["latency_ms"], 0)
        self.assertEqual(payload["source"], "PROJECT_BACKEND_RUN_STORE")
        self.assertTrue(deep_equal(payload["data"], self.fixture))
        Draft202012Validator(self.contract["success_payload"]).validate(payload)
        Draft202012Validator(self.schema).validate(payload["data"])
        self.assertIsNone(payload["data"]["output"]["root_cause"])
        self.assertIn("handoff_type", payload["data"]["output"])
        for key in ("quality_metrics", "token_usage", "latency", "cost"):
            self.assertIn(key, payload["data"])

    def test_auth_failures_are_exact(self):
        for supplied in (None, "Bearer wrong", "Basic " + AUTH_VALUE):
            with self.subTest(supplied=supplied):
                response = index.main(event(auth=supplied))
                self.assertEqual(response["statusCode"], 401)
                self.assertEqual(body(response), {"detail": "invalid_task_owned_test_credential"})

    def test_contract_rejections(self):
        response = index.main(event(query={"unexpected": "1"}, auth="Bearer " + AUTH_VALUE))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body(response), {"detail": "zero_parameter_contract_requires_empty_query"})
        response = index.main(event(method="POST", auth="Bearer " + AUTH_VALUE))
        self.assertEqual(response["statusCode"], 405)
        self.assertEqual(response["headers"]["Allow"], "GET")
        self.assertEqual(index.main(event(path="/wrong", auth="Bearer " + AUTH_VALUE))["statusCode"], 404)

    def test_empty_body_accepted_and_query_string_rejected(self):
        self.assertEqual(index.main(event(auth="Bearer " + AUTH_VALUE))["statusCode"], 200)
        request = event(path=index.TOOL_PATH + "?x=1", auth="Bearer " + AUTH_VALUE)
        self.assertEqual(index.main(request)["statusCode"], 400)
        for query_key, query_value in (("rawQueryString", "x=1"), ("multiValueQueryStringParameters", {"x": ["1"]})):
            request = event(auth="Bearer " + AUTH_VALUE)
            request[query_key] = query_value
            self.assertEqual(index.main(request)["statusCode"], 400)

    def test_missing_runtime_credential_fails_closed(self):
        os.environ.pop(index.AUTH_ENV_NAME)
        self.assertEqual(index.main(event(auth="Bearer " + AUTH_VALUE))["statusCode"], 401)

    def test_fixture_error_is_tool_error_with_http_200(self):
        original = index.FIXTURE_PATH
        try:
            with tempfile.TemporaryDirectory() as directory:
                index.FIXTURE_PATH = Path(directory) / "missing.json"
                response = index.main(event(auth="Bearer " + AUTH_VALUE))
        finally:
            index.FIXTURE_PATH = original
        payload = body(response)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(payload["status"], "ERROR")
        self.assertIsNone(payload["data"])
        self.assertEqual(payload["error"]["code"], "FIXTURE_LOAD_ERROR")

    def test_repeated_calls_have_same_data_and_no_business_state(self):
        first = body(index.main(event(auth="Bearer " + AUTH_VALUE)))
        second = body(index.main(event(auth="Bearer " + AUTH_VALUE)))
        self.assertTrue(deep_equal(first["data"], second["data"]))
        self.assertEqual(first["arguments"], {})
        self.assertEqual(second["arguments"], {})

    def test_synthetic_provenance_and_metric_types(self):
        output = self.fixture["output"]
        self.assertEqual(output["diagnosis_code"], "SYNTHETIC_DEMO_DATA")
        self.assertEqual(output["checks"]["data_origin"], "SYNTHETIC_DEMO_DATA")
        self.assertEqual(output["checks"]["fictional_experiment_id"], "synthetic-experiment-0001")
        self.assertFalse(output["checks"]["real_experiment_executed"])
        self.assertIsNone(output["handoff_type"])
        self.assertIsInstance(output["root_cause_evidence_refs"], list)
        self.assertTrue(all(x.startswith("synthetic-demo://") for x in output["root_cause_evidence_refs"]))
        self.assertIsNone(self.fixture["quality_metrics"]["candidate_reported_task_success"])
        metrics = [self.fixture["quality_metrics"]["candidate_reported_score"]]
        metrics += list(self.fixture["latency"].values())
        metrics += [self.fixture["cost"][k] for k in ("total", "model", "tool", "other")]
        metrics += list(self.fixture["token_usage"].values())
        for metric in metrics:
            self.assertEqual(metric["availability"], "ESTIMATED")
            self.assertEqual(metric["source"], "SYNTHETIC_DEMO_DATA")
            self.assertIn("not an experimental measurement", metric["note"])
            self.assertIsInstance(metric["value"], (int, float))
        for metric in self.fixture["token_usage"].values():
            self.assertIs(type(metric["value"]), int)

    def test_schema_rejects_invalid_nested_types_and_extra_fields(self):
        bad = copy.deepcopy(self.fixture)
        bad["token_usage"]["total_tokens"]["value"] = "18"
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(bad)
        bad = copy.deepcopy(self.fixture)
        bad["unexpected"] = "must be rejected"
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.schema).validate(bad)

    def test_zero_argument_request_schema(self):
        schema = json.loads((ROOT / "contract/REQUEST_SCHEMA.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate({})
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate({"run_id": "synthetic-run"})

    def test_fresh_process_returns_same_typed_synthetic_data(self):
        probe = "import importlib.util,json; s=importlib.util.spec_from_file_location('probe'," + repr(str(FUNCTION)) + "); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.main(" + repr(event(auth="Bearer " + AUTH_VALUE)) + ")))"
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                                encoding="utf-8", check=True, timeout=20, cwd=ROOT, env=os.environ.copy())
        response = json.loads(result.stdout)
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(deep_equal(body(response)["data"], self.fixture))

    def test_http_wrapper_on_owned_ephemeral_loopback_port(self):
        wrapper_spec = importlib.util.spec_from_file_location("public_cloudfunction_server", ROOT / "function/server.py")
        wrapper = importlib.util.module_from_spec(wrapper_spec)
        with patch.dict(sys.modules, {"index": index}):
            wrapper_spec.loader.exec_module(wrapper)
        server = wrapper.ThreadingHTTPServer(("127.0.0.1", 0), wrapper.RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            connection.request("GET", index.TOOL_PATH)
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            connection.request("GET", index.TOOL_PATH, headers={"Authorization": "Bearer " + AUTH_VALUE})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(deep_equal(json.loads(response.read())["data"], self.fixture))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
