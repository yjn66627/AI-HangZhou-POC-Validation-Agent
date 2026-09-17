from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from executor_gateway.tool_runtime import (
    AdapterExecution,
    BlockedInvocationAuditEvent,
    BlockedReason,
    CaseResourceBinding,
    FakeToolAdapter,
    InMemoryArtifactSink,
    InMemoryBindingResolver,
    ModelToolIntent,
    SideEffectClass,
    ToolError,
    ToolRegistry,
    ToolResultEnvelope,
    ToolRuntimeConfig,
    ToolRuntimeContext,
    ToolRuntimeCore,
    ToolRuntimeLimits,
    ToolRuntimeStatus,
    ToolSpec,
    assert_evidence_source_ref_is_real_success,
    blocked_event_to_workflow_projection,
    build_test_r3_unbound_registry,
    canonical_json_bytes,
    link_evidence_ref,
    runtime_status_to_workflow_status,
    sanitize_for_audit,
    sanitize_for_model_observation,
    sha256_artifact,
)
from experiment.evaluator import evaluate
from experiment.experiment_runner import run_experiment


FORMAL_TOOL = "测试只读工具"
EXECUTABLE_TOOL = "test_read_probe"
CASE_ID = "TEST-C1"
BINDING_ID = "binding-test-c1"


def _schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 128}},
    }


def _spec(**updates) -> ToolSpec:
    values = dict(
        formal_tool_name=FORMAL_TOOL,
        formal_capabilities=[FORMAL_TOOL],
        executable_tool_id=EXECUTABLE_TOOL,
        adapter_id="fake-readonly-adapter",
        adapter_version="test-only-v1",
        side_effect_class=SideEffectClass.READ_ONLY,
        argument_schema=_schema(),
        allowed_methods=["GET"],
        allowed_cases=[CASE_ID],
        enabled=True,
    )
    values.update(updates)
    return ToolSpec(**values)


def _binding(**updates) -> CaseResourceBinding:
    values = dict(
        case_binding_id=BINDING_ID,
        case_id=CASE_ID,
        environment="CONTROLLED_TEST",
        source_system="TEST_ONLY",
        allowed_executable_tools=[EXECUTABLE_TOOL],
        resource_refs={"resource": "test-only-resource"},
        read_only=True,
        binding_version="test-v1",
        created_at="2026-09-16T00:00:00Z",
    )
    values.update(updates)
    return CaseResourceBinding(**values)


def _context(**updates) -> ToolRuntimeContext:
    values = dict(
        run_id="run-c1",
        repeat_id="r1",
        case_id=CASE_ID,
        candidate_id="candidate-c1",
        case_binding_id=BINDING_ID,
        formal_allowed_tools=[FORMAL_TOOL],
        prohibited_tools=[],
        experiment_allowed_tools=[FORMAL_TOOL],
        candidate_allowed_tools=[FORMAL_TOOL],
    )
    values.update(updates)
    return ToolRuntimeContext(**values)


def _intent(sequence: int = 1, **updates) -> dict:
    values = dict(
        turn_type="TOOL_REQUEST",
        requested_tool=FORMAL_TOOL,
        arguments={"query": "hello"},
        request_sequence=sequence,
        model_message_ref=f"msg-{sequence}",
    )
    values.update(updates)
    return values


def _success_execution(data=None, *, latency_ms=5, response_artifact=None) -> AdapterExecution:
    data = data if data is not None else {"ok": True}
    response_artifact = response_artifact if response_artifact is not None else {"ok": True}
    return AdapterExecution(
        status=ToolRuntimeStatus.SUCCESS,
        data=data,
        error=None,
        latency_ms=latency_ms,
        response_artifact=response_artifact,
        source_system="TEST_ONLY",
        source_identifier="test-only-source",
        auth_scope="READ_ONLY",
    )


def _failure_execution(status: ToolRuntimeStatus, *, response_artifact=None, latency_ms=5) -> AdapterExecution:
    return AdapterExecution(
        status=status,
        data=None,
        error=ToolError(code=status.value, message="test-only failure", retriable=False),
        latency_ms=latency_ms,
        response_artifact=response_artifact,
        source_system="TEST_ONLY",
        source_identifier="test-only-source",
        auth_scope="READ_ONLY",
    )


def _core(*, adapter=None, spec=None, binding=None, limits=None, enabled=True, sink=None) -> ToolRuntimeCore:
    spec = spec or _spec()
    adapter = adapter or FakeToolAdapter(outcomes=[_success_execution()])
    return ToolRuntimeCore(
        registry=ToolRegistry([spec]),
        adapters={adapter.adapter_id: adapter},
        binding_resolver=InMemoryBindingResolver([binding or _binding()]),
        artifact_sink=sink or InMemoryArtifactSink(),
        config=ToolRuntimeConfig(enabled=enabled, limits=limits or ToolRuntimeLimits()),
    )


def test_model_tool_intent_forbids_model_supplied_tool_call_id():
    with pytest.raises(ValidationError):
        ModelToolIntent.model_validate({**_intent(), "tool_call_id": "tc_" + "a" * 32})


def test_runtime_parser_blocks_model_supplied_tool_call_id_without_tc_allocation():
    core = _core()
    outcome = core.process_intent({**_intent(), "tool_call_id": "tc_" + "a" * 32}, _context())
    assert outcome.blocked
    assert outcome.blocked_event.audit_event_id.startswith("ta_")
    assert not hasattr(outcome.blocked_event, "tool_call_id")
    assert core.state.issued_tool_call_ids == set()


def test_success_allocates_runtime_owned_tc_only_after_guard():
    core = _core()
    outcome = core.process_intent(_intent(), _context())
    assert outcome.result is not None
    assert outcome.result.tool_call_id.startswith("tc_")
    assert outcome.result.status == ToolRuntimeStatus.SUCCESS
    assert outcome.result.tool_call_id in core.state.issued_tool_call_ids


def test_tc_and_ta_namespaces_cannot_be_mixed_in_models():
    core = _core(spec=_spec(enabled=False))
    blocked = core.process_intent(_intent(), _context()).blocked_event
    assert blocked.audit_event_id.startswith("ta_")
    with pytest.raises(ValidationError):
        ToolResultEnvelope.model_validate({
            "tool_call_id": blocked.audit_event_id,
            "tool": FORMAL_TOOL,
            "executable_tool_id": EXECUTABLE_TOOL,
            "status": "SUCCESS",
            "data": {"ok": True},
            "error": None,
            "latency_ms": 1,
            "attempt": 1,
            "provenance": {
                "adapter_id": "x", "adapter_version": "1", "source_system": "TEST_ONLY",
                "source_identifier": "x", "observed_at": "2026-09-16T00:00:00Z", "auth_scope": "READ_ONLY",
                "request_artifact_sha256": "sha256:" + "0" * 64,
                "response_artifact_sha256": "sha256:" + "1" * 64,
            },
            "sanitization": {"credentials_removed": True, "sensitive_fields_removed": []},
            "audit_artifact_sha256": "sha256:" + "2" * 64,
        })


def test_blocked_event_extra_tool_call_id_is_rejected():
    core = _core(spec=_spec(enabled=False))
    blocked = core.process_intent(_intent(), _context()).blocked_event.model_dump()
    blocked["tool_call_id"] = "tc_" + "a" * 32
    with pytest.raises(ValidationError):
        BlockedInvocationAuditEvent.model_validate(blocked)


def test_registry_maps_formal_name_to_executable_id():
    registry = ToolRegistry([_spec()])
    assert registry.formal_to_executable(FORMAL_TOOL) == EXECUTABLE_TOOL
    assert registry.resolve_executable(EXECUTABLE_TOOL).formal_tool_name == FORMAL_TOOL


def test_test_r3_production_mappings_are_present_but_disabled():
    registry = build_test_r3_unbound_registry()
    assert registry.formal_to_executable("知识库测试结果") == "dify_kb_retrieval_probe"
    assert registry.formal_to_executable("对话流节点配置读取") == "dify_chatflow_retrieval_probe"
    assert registry.formal_to_executable("工作流版本/输入读取") == "dify_chatflow_retrieval_probe"
    assert registry.formal_to_executable("工具调用轨迹。") == "dify_chatflow_retrieval_probe"
    assert all(spec.enabled is False for spec in registry.specs())


def test_unknown_tool_is_blocked_before_tc():
    core = _core()
    outcome = core.process_intent(_intent(requested_tool="不存在工具"), _context(formal_allowed_tools=["不存在工具"]))
    assert outcome.blocked_event.blocked_reason == BlockedReason.UNKNOWN_TOOL
    assert not core.state.issued_tool_call_ids


def test_disabled_tool_is_blocked_before_tc():
    core = _core(spec=_spec(enabled=False))
    outcome = core.process_intent(_intent(), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.REGISTRY_DISABLED
    assert not core.state.issued_tool_call_ids


def test_formal_allowlist_is_enforced():
    core = _core()
    outcome = core.process_intent(_intent(), _context(formal_allowed_tools=[]))
    assert outcome.blocked_event.blocked_reason == BlockedReason.CASE_NOT_ALLOWED


def test_prohibited_tool_is_enforced():
    core = _core()
    outcome = core.process_intent(_intent(), _context(prohibited_tools=[FORMAL_TOOL]))
    assert outcome.blocked_event.blocked_reason == BlockedReason.PROHIBITED_TOOL


def test_non_read_only_spec_is_blocked():
    core = _core(spec=_spec(side_effect_class=SideEffectClass.WRITE))
    outcome = core.process_intent(_intent(), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.NON_READ_ONLY_OPERATION


def test_unsafe_http_method_is_blocked_by_runtime_policy():
    core = _core(spec=_spec(allowed_methods=["POST"]))
    outcome = core.process_intent(_intent(), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.NON_READ_ONLY_OPERATION


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"query": "x", "api_key": "secret"}, BlockedReason.CREDENTIAL_FIELD_FORBIDDEN),
        ({"query": "x", "base_url": "https://evil.example"}, BlockedReason.ARBITRARY_URL),
        ({"query": "https://evil.example"}, BlockedReason.ARBITRARY_URL),
        ({"query": "x", "workflow_id": "arbitrary"}, BlockedReason.ARBITRARY_RESOURCE_ID),
    ],
)
def test_guard_rejects_credential_url_and_resource_injection(arguments, expected):
    permissive = _spec(argument_schema={"type": "object", "additionalProperties": True})
    core = _core(spec=permissive)
    outcome = core.process_intent(_intent(arguments=arguments), _context())
    assert outcome.blocked_event.blocked_reason == expected
    assert not core.state.issued_tool_call_ids


def test_argument_schema_validation_blocks_invalid_arguments():
    core = _core()
    outcome = core.process_intent(_intent(arguments={"query": "ok", "extra": 1}), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.INVALID_ARGUMENTS


def test_wrong_case_binding_is_blocked():
    core = _core(binding=_binding(allowed_executable_tools=[]))
    outcome = core.process_intent(_intent(), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.WRONG_CASE_BINDING


def test_replay_is_blocked():
    adapter = FakeToolAdapter(outcomes=[_success_execution(), _success_execution()])
    core = _core(adapter=adapter, limits=ToolRuntimeLimits(max_calls_per_tool=2))
    first = core.process_intent(_intent(), _context())
    assert first.result is not None
    replay = core.process_intent(_intent(sequence=2, model_message_ref="msg-1"), _context())
    assert replay.blocked_event.blocked_reason == BlockedReason.REPLAY_DETECTED


def test_out_of_order_sequence_is_blocked():
    core = _core()
    outcome = core.process_intent(_intent(sequence=2), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.REQUEST_SEQUENCE_INVALID


def test_per_tool_call_budget_is_enforced():
    adapter = FakeToolAdapter(outcomes=[_success_execution(), _success_execution()])
    core = _core(adapter=adapter)
    assert core.process_intent(_intent(), _context()).result is not None
    second = core.process_intent(_intent(sequence=2), _context())
    assert second.blocked_event.blocked_reason == BlockedReason.BUDGET_EXHAUSTED
    assert len(adapter.calls) == 1


def test_max_request_rounds_is_enforced_without_retry():
    limits = ToolRuntimeLimits(max_tool_request_rounds=1, max_calls_per_tool=2)
    adapter = FakeToolAdapter(outcomes=[_success_execution(), _success_execution()])
    core = _core(adapter=adapter, limits=limits)
    assert core.process_intent(_intent(), _context()).result is not None
    second = core.process_intent(_intent(sequence=2), _context())
    assert second.blocked_event.blocked_reason == BlockedReason.BUDGET_EXHAUSTED
    assert len(adapter.calls) == 1


def test_feature_gate_is_disabled_by_default_and_legacy_path_is_not_wired():
    core = ToolRuntimeCore(
        registry=ToolRegistry([_spec()]),
        adapters={"fake-readonly-adapter": FakeToolAdapter()},
        binding_resolver=InMemoryBindingResolver([_binding()]),
    )
    assert core.config.enabled is False
    with pytest.raises(RuntimeError, match="tool_runtime_disabled"):
        core.process_intent(_intent(), _context())


@pytest.mark.parametrize(
    "status,workflow_status",
    [
        (ToolRuntimeStatus.SUCCESS, "SUCCESS"),
        (ToolRuntimeStatus.TIMEOUT, "ERROR"),
        (ToolRuntimeStatus.AUTH_ERROR, "ERROR"),
        (ToolRuntimeStatus.HTTP_4XX, "ERROR"),
        (ToolRuntimeStatus.HTTP_5XX, "ERROR"),
        (ToolRuntimeStatus.TOOL_ERROR, "ERROR"),
        (ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR, "ERROR"),
        (ToolRuntimeStatus.SAFETY_BLOCKED, "BLOCKED"),
    ],
)
def test_failure_mapping(status, workflow_status):
    assert runtime_status_to_workflow_status(status) == workflow_status


@pytest.mark.parametrize(
    "status",
    [
        ToolRuntimeStatus.TIMEOUT,
        ToolRuntimeStatus.AUTH_ERROR,
        ToolRuntimeStatus.HTTP_4XX,
        ToolRuntimeStatus.HTTP_5XX,
        ToolRuntimeStatus.TOOL_ERROR,
        ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR,
        ToolRuntimeStatus.SAFETY_BLOCKED,
    ],
)
def test_runtime_failure_statuses_create_real_tc_but_never_success(status):
    response = None if status == ToolRuntimeStatus.TIMEOUT else {"error": status.value}
    adapter = FakeToolAdapter(outcomes=[_failure_execution(status, response_artifact=response)])
    core = _core(adapter=adapter)
    outcome = core.process_intent(_intent(), _context())
    assert outcome.result.tool_call_id.startswith("tc_")
    assert outcome.result.status == status
    assert outcome.tool_trace["status"] != "SUCCESS"


def test_timeout_has_nullable_response_hash():
    adapter = FakeToolAdapter(outcomes=[_failure_execution(ToolRuntimeStatus.TIMEOUT, response_artifact=None)])
    result = _core(adapter=adapter).process_intent(_intent(), _context()).result
    assert result.provenance.response_artifact_sha256 is None
    assert result.provenance.request_artifact_sha256.startswith("sha256:")
    assert result.audit_artifact_sha256.startswith("sha256:")


def test_success_has_request_response_and_audit_hashes():
    result = _core().process_intent(_intent(), _context()).result
    assert result.provenance.request_artifact_sha256.startswith("sha256:")
    assert result.provenance.response_artifact_sha256.startswith("sha256:")
    assert result.audit_artifact_sha256.startswith("sha256:")


def test_fake_adapter_provenance_is_unambiguously_test_only():
    result = _core().process_intent(_intent(), _context()).result
    assert result.provenance.source_system == "TEST_ONLY"
    assert "test-only" in result.provenance.source_identifier
    assert result.provenance.auth_scope == "READ_ONLY"


def test_adapter_is_never_automatically_retried():
    adapter = FakeToolAdapter(outcomes=[_failure_execution(ToolRuntimeStatus.HTTP_5XX, response_artifact={"status": 500})])
    outcome = _core(adapter=adapter).process_intent(_intent(), _context())
    assert outcome.result.status == ToolRuntimeStatus.HTTP_5XX
    assert outcome.result.attempt == 1
    assert len(adapter.calls) == 1


def test_adapter_response_size_limit_fails_closed():
    payload = {"blob": "x" * 4096}
    limits = ToolRuntimeLimits(max_adapter_response_bytes=1024, max_model_visible_observation_bytes=1024)
    adapter = FakeToolAdapter(outcomes=[_success_execution(data=payload, response_artifact=payload)])
    outcome = _core(adapter=adapter, limits=limits).process_intent(_intent(), _context())
    assert outcome.result.status == ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR
    assert outcome.tool_trace["status"] == "ERROR"


def test_model_observation_is_size_limited_and_truncated_without_secret():
    data = {"blob": "x" * 3000}
    limits = ToolRuntimeLimits(max_adapter_response_bytes=8192, max_model_visible_observation_bytes=1024)
    adapter = FakeToolAdapter(outcomes=[_success_execution(data=data, response_artifact=data)])
    outcome = _core(adapter=adapter, limits=limits).process_intent(_intent(), _context())
    assert len(canonical_json_bytes(outcome.model_observation.model_dump())) <= 1024
    assert outcome.model_observation.data["_observation_truncated"] is True


def test_blocked_projection_has_no_tool_trace_and_marks_guardrail():
    blocked = _core(spec=_spec(enabled=False)).process_intent(_intent(), _context()).blocked_event
    projection = blocked_event_to_workflow_projection(blocked)
    assert projection["status"] == "BLOCKED"
    assert projection["tool_trace"] == []
    assert projection["errors"][0]["code"] == "TOOL_INVOCATION_GUARD_BLOCKED"
    assert projection["output_patch"] == {"guardrail_triggered": True, "guardrail_blocked": True}


def test_blocked_event_is_not_evidence_eligible():
    blocked = _core(spec=_spec(enabled=False)).process_intent(_intent(), _context()).blocked_event
    assert blocked.evidence_eligible is False
    with pytest.raises(ValueError, match="blocked_audit_event"):
        assert_evidence_source_ref_is_real_success(blocked.audit_event_id, [])


def test_success_evidence_linkage_uses_exact_tc_only():
    outcome = _core().process_intent(_intent(), _context())
    trace = [outcome.tool_trace]
    tc = outcome.result.tool_call_id
    row = assert_evidence_source_ref_is_real_success(tc, trace)
    assert row["tool_call_id"] == tc
    link_evidence_ref(trace, evidence_id="ev-1", source_ref=tc)
    assert trace[0]["evidence_refs"] == ["ev-1"]


@pytest.mark.parametrize("source_ref", ["unknown", "测试只读工具", "ta_" + "a" * 32, "tc_" + "b" * 32])
def test_invalid_or_fabricated_evidence_refs_fail_closed(source_ref):
    outcome = _core().process_intent(_intent(), _context())
    with pytest.raises(ValueError):
        assert_evidence_source_ref_is_real_success(source_ref, [outcome.tool_trace])


@pytest.mark.parametrize("status", [ToolRuntimeStatus.TIMEOUT, ToolRuntimeStatus.HTTP_4XX, ToolRuntimeStatus.SAFETY_BLOCKED])
def test_non_success_tc_cannot_be_evidence(status):
    adapter = FakeToolAdapter(outcomes=[_failure_execution(status, response_artifact=None if status == ToolRuntimeStatus.TIMEOUT else {"e": 1})])
    outcome = _core(adapter=adapter).process_intent(_intent(), _context())
    with pytest.raises(ValueError, match="not_successful_tool_result"):
        assert_evidence_source_ref_is_real_success(outcome.result.tool_call_id, [outcome.tool_trace])


def test_canonical_hash_is_order_independent_and_audit_sanitizer_redacts_credentials():
    assert sha256_artifact({"b": 2, "a": 1}) == sha256_artifact({"a": 1, "b": 2})
    sanitized, removed = sanitize_for_audit({"query": "x", "api_key": "super-secret"})
    assert sanitized["api_key"] == "[REDACTED]"
    assert removed == ["api_key"]
    sink = InMemoryArtifactSink()
    digest = sink.put("x", {"api_key": "super-secret"})
    assert "super-secret" not in str(sink.artifacts[digest])


def test_evaluator_accepts_exact_tool_call_id_source_ref(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="c1-exact-source")
    assert w["evidence"][0]["source_ref"] == w["tool_trace"][0]["tool_call_id"]
    e = evaluate(w, b["case_spec"], b["experiment_spec"], b["task"], b["candidate"])
    assert e["evidence"]["status"] == "SUFFICIENT"


def test_evaluator_rejects_legacy_tool_name_encoded_source_ref(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="c1-legacy-source")
    call = w["tool_trace"][0]
    w["evidence"][0]["source_ref"] = f"tool:{call['tool']}:{call['tool_call_id']}"
    e = evaluate(w, b["case_spec"], b["experiment_spec"], b["task"], b["candidate"])
    assert e["evidence"]["status"] == "INSUFFICIENT"
    assert any("tool_trace_source_mismatch" in reason or "tool_observation_source_not_successful_tool_call" in reason for reason in e["evidence"]["reasons"])


def test_guard_block_error_is_recognized_as_safety_fact(success_bundle):
    b = deepcopy(success_bundle)
    w = run_experiment(b["task"], b["candidate"], b["experiment_spec"], run_id="c1-guard-block")
    w["status"] = "BLOCKED"
    w["output"]["guardrail_triggered"] = True
    w["output"]["guardrail_blocked"] = True
    w["output"]["final_action"] = "REFUSE"
    w["errors"].append({
        "code": "TOOL_INVOCATION_GUARD_BLOCKED",
        "message": "PROHIBITED_TOOL; audit_ref=ta_" + "a" * 32,
        "source": "RUNTIME",
        "retriable": False,
    })
    e = evaluate(w, b["case_spec"], b["experiment_spec"], b["task"], b["candidate"])
    assert "blocked_invocation_guard" in e["safety"]["violation_reasons"]
    assert e["severe_error"] is True


def test_observation_redacts_authorization_field():
    secret = "Bearer TOPSECRET-XYZ"
    adapter = FakeToolAdapter(outcomes=[_success_execution(
        data={"authorization": secret, "ok": True},
        response_artifact={"authorization": secret, "ok": True},
    )])
    outcome = _core(adapter=adapter).process_intent(_intent(), _context())
    assert outcome.model_observation.data["authorization"] == "[REDACTED]"
    assert secret not in str(outcome.model_observation.model_dump())


def test_observation_redacts_nested_authorization_and_list_secret_values():
    bearer = "Bearer NESTED-SECRET-123"
    sk = "sk-" + "proj-" + "SUPERSECRET123"
    data = {"nested": {"Authorization": bearer}, "items": [{"value": sk}, ("safe", bearer)]}
    safe, removed = sanitize_for_model_observation(data)
    assert safe["nested"]["Authorization"] == "[REDACTED]"
    assert safe["items"][0]["value"] == "[REDACTED]"
    assert safe["items"][1][1] == "[REDACTED]"
    assert bearer not in str(safe) and sk not in str(safe)
    assert removed


def test_model_observation_redacts_bearer_and_sk_proj_values_without_sensitive_keys():
    bearer = "Bearer TOPSECRET-ABC123"
    sk = "my key is " + "sk-" + "proj-" + "SUPERSECRET456"
    adapter = FakeToolAdapter(outcomes=[_success_execution(
        data={"message": bearer, "note": sk},
        response_artifact={"message": bearer, "note": sk},
    )])
    outcome = _core(adapter=adapter).process_intent(_intent(), _context())
    dumped = str(outcome.model_observation.model_dump())
    assert "TOPSECRET" not in dumped
    assert "SUPERSECRET" not in dumped
    assert outcome.result.data["message"] == "[REDACTED]"
    assert outcome.result.data["note"] == "[REDACTED]"


def test_audit_and_persisted_artifacts_never_contain_raw_secret_values():
    secret = "Bearer PERSIST-ME-NOT-123"
    sink = InMemoryArtifactSink()
    adapter = FakeToolAdapter(outcomes=[_success_execution(
        data={"nested": {"authorization": secret}},
        response_artifact={"nested": {"authorization": secret}},
    )])
    outcome = _core(adapter=adapter, sink=sink).process_intent(_intent(), _context())
    assert secret not in str(sink.artifacts)
    assert secret not in str(outcome.result.model_dump())
    assert secret not in str(outcome.model_observation.model_dump())


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "x", "authorization": "Bearer SECRET-123456"},
        {"query": "x", "nested": {"client_secret": "abc123"}},
        {"query": "my key is " + "sk-" + "proj-" + "SUPERSECRET789"},
        {"query": "token=VERYSECRET123"},
    ],
)
def test_credential_like_arguments_block_before_tc_and_adapter_call(arguments):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": True,
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
    }
    adapter = FakeToolAdapter(outcomes=[_success_execution()])
    core = _core(adapter=adapter, spec=_spec(argument_schema=schema))
    outcome = core.process_intent(_intent(arguments=arguments), _context())
    assert outcome.blocked_event is not None
    assert outcome.blocked_event.audit_event_id.startswith("ta_")
    assert core.state.issued_tool_call_ids == set()
    assert len(adapter.calls) == 0
    assert "SECRET" not in str(outcome.blocked_event.model_dump())


def test_high_confidence_credential_value_uses_stable_block_reason():
    core = _core()
    outcome = core.process_intent(_intent(arguments={"query": "my key is " + "sk-" + "proj-" + "SUPERSECRET"}), _context())
    assert outcome.blocked_event.blocked_reason == BlockedReason.CREDENTIAL_LIKE_ARGUMENT_BLOCKED


def test_sanitizer_does_not_redact_security_metadata_fields():
    payload = {
        "credentials_removed": True,
        "sanitization_state": "COMPLETE",
        "evidence_eligible": False,
        "external_call_started": False,
    }
    sanitized, removed = sanitize_for_audit(payload)
    assert sanitized == payload
    assert removed == []


def _core_with_adapter_bound_under_expected_key(adapter, spec=None, sink=None):
    spec = spec or _spec()
    return ToolRuntimeCore(
        registry=ToolRegistry([spec]),
        adapters={spec.adapter_id: adapter},
        binding_resolver=InMemoryBindingResolver([_binding()]),
        artifact_sink=sink or InMemoryArtifactSink(),
        config=ToolRuntimeConfig(enabled=True),
    )


def test_adapter_identity_match_executes_and_provenance_uses_verified_runtime_identity():
    adapter = FakeToolAdapter(adapter_id="fake-readonly-adapter", adapter_version="test-only-v1", outcomes=[_success_execution()])
    outcome = _core_with_adapter_bound_under_expected_key(adapter).process_intent(_intent(), _context())
    assert len(adapter.calls) == 1
    assert outcome.result.status == ToolRuntimeStatus.SUCCESS
    assert outcome.result.provenance.adapter_id == adapter.adapter_id
    assert outcome.result.provenance.adapter_version == adapter.adapter_version


@pytest.mark.parametrize(
    "adapter_id,adapter_version",
    [
        ("wrong-adapter-object", "test-only-v1"),
        ("fake-readonly-adapter", "WRONG-v9"),
    ],
)
def test_adapter_identity_mismatch_blocks_without_invocation(adapter_id, adapter_version):
    adapter = FakeToolAdapter(adapter_id=adapter_id, adapter_version=adapter_version, outcomes=[_success_execution()])
    core = _core_with_adapter_bound_under_expected_key(adapter)
    outcome = core.process_intent(_intent(), _context())
    assert len(adapter.calls) == 0
    assert outcome.result.tool_call_id.startswith("tc_")
    assert outcome.result.status == ToolRuntimeStatus.SAFETY_BLOCKED
    assert outcome.tool_trace["status"] == "BLOCKED"
    assert outcome.result.error.code == "ADAPTER_IDENTITY_MISMATCH"
    assert outcome.result.provenance.adapter_id == adapter_id
    assert outcome.result.provenance.adapter_version == adapter_version
    with pytest.raises(ValueError, match="not_successful_tool_result"):
        assert_evidence_source_ref_is_real_success(outcome.result.tool_call_id, [outcome.tool_trace])


def test_adapter_identity_mismatch_cannot_produce_success_evidence():
    adapter = FakeToolAdapter(adapter_id="wrong-adapter-object", outcomes=[_success_execution()])
    outcome = _core_with_adapter_bound_under_expected_key(adapter).process_intent(_intent(), _context())
    assert outcome.result.status == ToolRuntimeStatus.SAFETY_BLOCKED
    with pytest.raises(ValueError):
        link_evidence_ref([outcome.tool_trace], evidence_id="ev-bad", source_ref=outcome.result.tool_call_id)


def test_elapsed_time_budget_normalizes_late_success_to_timeout_without_claiming_hard_interrupt():
    adapter = FakeToolAdapter(outcomes=[_success_execution(latency_ms=0)])
    limits = ToolRuntimeLimits(timeout_per_call_ms=10, total_tool_execution_budget_ms=20_000)
    core = _core(adapter=adapter, limits=limits)
    with patch("executor_gateway.tool_runtime.time.monotonic", side_effect=[100.0, 100.020]):
        outcome = core.process_intent(_intent(), _context())
    assert outcome.result.status == ToolRuntimeStatus.TIMEOUT
    assert outcome.result.provenance.response_artifact_sha256 is None
    assert len(adapter.calls) == 1


def test_oversized_response_is_rejected_before_model_observation_and_secret_is_not_persisted():
    secret = "Bearer OVERSIZED-SECRET-123456"
    payload = {"authorization": secret, "blob": "x" * 4096}
    sink = InMemoryArtifactSink()
    limits = ToolRuntimeLimits(max_adapter_response_bytes=1024, max_model_visible_observation_bytes=1024)
    adapter = FakeToolAdapter(outcomes=[_success_execution(data=payload, response_artifact=payload)])
    outcome = _core(adapter=adapter, limits=limits, sink=sink).process_intent(_intent(), _context())
    assert outcome.result.status == ToolRuntimeStatus.RESPONSE_VALIDATION_ERROR
    assert outcome.result.data is None
    assert outcome.model_observation.data is None
    assert secret not in str(sink.artifacts)
    assert outcome.result.provenance.response_artifact_sha256 is None
