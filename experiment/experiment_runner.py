from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from uuid import uuid4

from .executor_base import ExperimentExecutor, LiveExecutionUnavailable
from .schemas import utc_now, validate_linked_inputs, validate_workflow_result


def metric(value: float | int | None, availability: str = "AVAILABLE", *, source: str | None = "FIXTURE", note: str | None = None) -> dict[str, Any]:
    if availability in {"NOT_PROVIDED", "NOT_APPLICABLE"}:
        value = None
    if availability == "ESTIMATED" and (not source or not note):
        raise ValueError("estimated_metric_requires_source_and_note")
    return {"value": value, "availability": availability, "source": source, "note": note}


def _trace(call_id: str, tool: str, status: str, evidence_refs: list[str], *, error: Any = None, result: Any = None, latency_ms: float = 80, unauthorized: bool = False) -> dict[str, Any]:
    return {
        "tool_call_id": call_id,
        "tool": tool,
        "status": status,
        "arguments": {},
        "result": result,
        "error": error,
        "latency_ms": metric(latency_ms, source="FIXTURE"),
        "retry_count": 0,
        "evidence_refs": evidence_refs,
        "unauthorized_attempt": unauthorized,
    }




def _select_fixture_tool(task: Mapping[str, Any], candidate: Mapping[str, Any], spec: Mapping[str, Any]) -> str | None:
    """选择已声明且被Task允许的fixture工具；绝不凭空补默认工具。"""
    task_tools = set(task.get("available_tools") or [])
    required = list(spec.get("required_tools") or [])
    candidate_tools = list(candidate.get("tools") or [])
    for tool in required:
        if tool in task_tools and tool in candidate_tools:
            return str(tool)
    for tool in candidate_tools:
        if tool in task_tools:
            return str(tool)
    return None


def _require_declared_fixture_tool(
    tool: str, task: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    if tool not in set(task.get("available_tools") or []) or tool not in set(candidate.get("tools") or []):
        raise ValueError(f"fixture_profile_requires_declared_tool:{tool}")
    return tool

def _base_result(task: Mapping[str, Any], candidate: Mapping[str, Any], spec: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    mode = spec["execution_mode"]
    kind = {"FIXTURE": "FIXTURE", "MOCK": "MOCK", "CONTROLLED_FAULT": "CONTROLLED_FAULT"}[mode]
    now = utc_now()
    primary_tool = _select_fixture_tool(task, candidate, spec)
    tool_trace = []
    evidence = []
    if primary_tool is not None:
        tool_trace = [_trace("call-1", primary_tool, "SUCCESS", ["ev-1"], result={"matched": True, "items": 3})]
        evidence = [{
            "evidence_id": "ev-1", "evidence_type": "TOOL_OBSERVATION", "claim": "已声明工具返回了可用观测。",
            "source_ref": "call-1",
            "support_level": "SUPPORTS", "content": "matched=true, items=3",
            "claim_ids": ["tool_observation"], "target": str(task["case_id"]), "action": "retrieve", "result": "matched=true, items=3",
        }]
    return {
        "schema_version": "2.2",
        "run_id": run_id,
        "case_id": task["case_id"],
        "candidate_id": candidate["candidate_id"],
        "experiment_id": spec["experiment_id"],
        "status": "SUCCESS",
        "source": {
            "kind": kind,
            "provider": "sandbox-controlled-runner",
            "adapter_id": "fixture-runner-v2",
            "reference": run_id,
            "is_fixture": True,
            "is_mock": mode == "MOCK",
            "fixture_reason": f"SANDBOX_{mode}_ONLY",
        },
        "run_mode": mode,
        "output": {
            "final_action": "ANSWER",
            "diagnosis_code": "TASK_COMPLETED",
            "response": "受控沙箱执行完成。",
            "root_cause": None,
            "root_cause_evidence_refs": [],
            "confidence": "MEDIUM",
            "handoff_type": None,
            "guardrail_blocked": False,
            "guardrail_triggered": False,
            "checks": {},
        },
        "quality_metrics": {
            "candidate_reported_task_success": True,
            "candidate_reported_score": metric(0.92, source="FIXTURE_CANDIDATE_SELF_REPORT"),
            "metric_breakdown": {"task_fit": 0.94, "groundedness": 0.90},
        },
        "latency": {
            "total_ms": metric(820.0),
            "model_ms": metric(600.0 if primary_tool is not None else 780.0),
            "tool_ms": metric(180.0 if primary_tool is not None else 0.0),
            "queue_ms": metric(40.0),
        },
        "cost": {
            "currency": spec["success_criteria"]["cost_currency"], "currency_availability": "AVAILABLE",
            "total": metric(0.018), "model": metric(0.016), "tool": metric(0.002), "other": metric(0.0),
        },
        "token_usage": {
            "input_tokens": metric(520), "output_tokens": metric(180), "total_tokens": metric(700),
            "cache_hit_tokens": metric(0), "cache_miss_tokens": metric(520),
        },
        "tool_trace": tool_trace,
        "errors": [],
        "evidence": evidence,
        "provenance": {
            "execution_id": run_id, "producer": "experiment_runner.fixture", "adapter_id": "fixture-runner-v2",
            "source_endpoint": None, "captured_at": now, "environment": "SANDBOX", "raw_response_ref": None, "executor_type": {"FIXTURE":"FIXTURE_EXECUTOR","MOCK":"MOCK_EXECUTOR","CONTROLLED_FAULT":"CONTROLLED_FAULT_EXECUTOR"}[mode], "remote_execution_id": None,
        },
        "timestamps": {"started_at": now, "finished_at": now, "remote_availability": "AVAILABLE", "received_at": now},
    }


def build_fixture_result(task: Mapping[str, Any], candidate: Mapping[str, Any], spec: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    result = _base_result(task, candidate, spec, run_id)
    profile = spec["simulation"]["profile"]

    if profile == "NORMAL_SUCCESS":
        pass
    elif profile == "QUALITY_LOW":
        result["output"].update({"diagnosis_code": "LOW_QUALITY_OUTPUT", "response": "结果可生成，但未满足Gold/验收规则。", "handoff_type": "QUALITY"})
        result["quality_metrics"].update({"candidate_reported_task_success": True, "candidate_reported_score": metric(0.95, source="FIXTURE_CANDIDATE_SELF_REPORT")})
        # 独立Evaluator会因为诊断/Gold规则、Evidence关键词等判低，不信任0.95自报分。
        if result["evidence"]:
            result["evidence"][0]["claim"] = "工具返回了内容，但没有证明输出满足关键验收事实。"
            result["evidence"][0]["content"] = "content_received=true"
    elif profile == "TOOL_TIMEOUT":
        result["status"] = "TIMEOUT"
        result["output"].update({"final_action": "HANDOFF", "diagnosis_code": "TOOL_TIMEOUT", "response": "关键工具超时，停止自信结论并转人工复核。", "confidence": "LOW", "handoff_type": "RUNTIME"})
        result["quality_metrics"].update({"candidate_reported_task_success": False, "candidate_reported_score": metric(0.25, source="FIXTURE_CANDIDATE_SELF_REPORT")})
        primary_tool = _select_fixture_tool(task, candidate, spec)
        if primary_tool is None:
            result["tool_trace"] = []
            result["errors"] = [{"code": "no_declared_tool", "message": "受控超时profile没有可声明工具可调用", "source": "RUNNER", "retriable": False}]
            result["evidence"] = []
        else:
            result["tool_trace"] = [_trace("call-1", primary_tool, "ERROR", ["ev-timeout"], error={"code": "timeout", "message": "controlled timeout"}, result=None, latency_ms=1500)]
            result["errors"] = [{"code": "timeout", "message": "controlled timeout", "source": "TOOL", "retriable": True}]
            result["evidence"] = [{"evidence_id": "ev-timeout", "evidence_type": "ERROR", "claim": "关键工具发生受控超时。", "source_ref": "call-1", "support_level": "SUPPORTS", "content": "timeout", "claim_ids": ["tool_timeout"], "target": str(task["case_id"]), "action": "tool_call", "result": "timeout"}]
        result["latency"] = {"total_ms": metric(1580.0), "model_ms": metric(40.0), "tool_ms": metric(1500.0), "queue_ms": metric(40.0)}
        result["cost"] = {"currency": spec["success_criteria"]["cost_currency"], "currency_availability": "AVAILABLE", "total": metric(0.003), "model": metric(0.003), "tool": metric(0.0), "other": metric(0.0)}
    elif profile == "EVIDENCE_MISSING":
        result["status"] = "PARTIAL"
        result["output"].update({"final_action": "HANDOFF", "diagnosis_code": "EVIDENCE_INSUFFICIENT", "response": "结果文本存在，但缺少可追溯证据，转人工补证。", "confidence": "LOW", "handoff_type": "EVIDENCE"})
        result["quality_metrics"].update({"candidate_reported_task_success": True, "candidate_reported_score": metric(0.99, source="FIXTURE_CANDIDATE_SELF_REPORT")})
        primary_tool = _select_fixture_tool(task, candidate, spec)
        result["tool_trace"] = [] if primary_tool is None else [_trace("call-1", primary_tool, "SUCCESS", [], result={"matched": True, "items": 2})]
        result["evidence"] = []
    elif profile == "HIGH_RISK_PERMISSION":
        result["status"] = "BLOCKED"
        result["output"].update({"final_action": "REFUSE", "diagnosis_code": "PERMISSION_BOUNDARY", "response": "检测到未授权写操作请求，护栏阻断并转人工。", "root_cause": "当前身份不具备写操作权限", "root_cause_evidence_refs": ["ev-permission"], "confidence": "HIGH", "handoff_type": "POLICY", "guardrail_blocked": True, "guardrail_triggered": True, "checks": {"unauthorized_action": False}})
        result["quality_metrics"].update({"candidate_reported_task_success": False, "candidate_reported_score": metric(0.70, source="FIXTURE_CANDIDATE_SELF_REPORT")})
        read_tool = _require_declared_fixture_tool("read_permission_scope", task, candidate)
        write_tool = _require_declared_fixture_tool("write_resource", task, candidate)
        result["tool_trace"] = [
            _trace("call-1", read_tool, "SUCCESS", ["ev-permission"], result={"can_write": False}),
            _trace("call-2", write_tool, "BLOCKED", ["ev-policy"], error={"code": "policy_block", "message": "write denied"}, unauthorized=True),
        ]
        result["errors"] = [{"code": "policy_block", "message": "write denied", "source": "POLICY", "retriable": False}]
        result["evidence"] = [
            {"evidence_id": "ev-permission", "evidence_type": "TOOL_OBSERVATION", "claim": "当前身份没有写权限。", "source_ref": "call-1", "support_level": "SUPPORTS", "content": "can_write=false", "claim_ids": ["permission_scope"], "target": str(task["case_id"]), "action": "read_permission", "result": "can_write=false"},
            {"evidence_id": "ev-policy", "evidence_type": "POLICY", "claim": "写操作已被安全策略阻断。", "source_ref": "call-2", "support_level": "SUPPORTS", "content": "policy_block", "claim_ids": ["policy_block"], "target": str(task["case_id"]), "action": "write_resource", "result": "blocked"},
        ]
    elif profile == "SAFE_GUARDRAIL_REFUSAL":
        result["status"] = "SUCCESS"
        result["output"].update({"final_action": "REFUSE", "diagnosis_code": "POLICY_REFUSAL", "response": "请求触及受控边界，已安全拒绝并给出替代路径。", "confidence": "HIGH", "handoff_type": "POLICY", "guardrail_blocked": True, "guardrail_triggered": True})
        read_tool = _require_declared_fixture_tool("read_permission_scope", task, candidate)
        result["tool_trace"] = [_trace("call-1", read_tool, "SUCCESS", ["ev-safe"], result={"allowed": False})]
        result["evidence"] = [{"evidence_id": "ev-safe", "evidence_type": "POLICY", "claim": "策略要求拒绝当前操作。", "source_ref": "call-1", "support_level": "SUPPORTS", "content": "allowed=false", "claim_ids": ["policy_refusal"], "target": str(task["case_id"]), "action": "policy_check", "result": "refuse"}]
    elif profile == "PARTIAL_OUTPUT":
        result["status"] = "PARTIAL"
        result["output"].update({"final_action": "ANSWER", "diagnosis_code": "TASK_COMPLETED", "response": "仅获得部分结果。", "confidence": "LOW"})
    elif profile == "METRICS_MISSING":
        result["latency"] = {k: metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM") for k in ("total_ms", "model_ms", "tool_ms", "queue_ms")}
        result["cost"] = {
            "currency": None, "currency_availability": "NOT_PROVIDED",
            "total": metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM"), "model": metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM"),
            "tool": metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM"), "other": metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM"),
        }
        result["token_usage"] = {k: metric(None, "NOT_PROVIDED", source="FIXTURE_PLATFORM") for k in ("input_tokens", "output_tokens", "total_tokens", "cache_hit_tokens", "cache_miss_tokens")}
    else:
        raise ValueError(f"unsupported_simulation_profile:{profile}")

    return validate_workflow_result(result)


class FixtureExecutor(ExperimentExecutor):
    def execute(self, *, task: Mapping[str, Any], candidate: Mapping[str, Any], experiment_spec: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        if experiment_spec["execution_mode"] == "LIVE":
            raise LiveExecutionUnavailable("FixtureExecutor不能执行LIVE。")
        return build_fixture_result(task, candidate, experiment_spec, run_id)


def run_experiment(
    task: Mapping[str, Any],
    candidate: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    run_id: str | None = None,
    executor: ExperimentExecutor | None = None,
    live_executor: ExperimentExecutor | None = None,
) -> dict[str, Any]:
    """执行一次实验。LIVE必须显式提供真实执行器；Gold永远不进入执行器。"""
    validate_linked_inputs(task, candidate, spec)
    run_id = run_id or f"run-{uuid4().hex[:12]}"

    if spec["execution_mode"] == "LIVE":
        chosen = live_executor or executor
        if chosen is None:
            raise LiveExecutionUnavailable("LIVE需要可注入的真实执行器；当前未配置。")
    else:
        chosen = executor or FixtureExecutor()

    result = chosen.execute(
        task=deepcopy(dict(task)), candidate=deepcopy(dict(candidate)), experiment_spec=deepcopy(dict(spec)), run_id=run_id
    )
    validated = validate_workflow_result(result)
    for key, expected in (("run_id", run_id), ("case_id", task["case_id"]), ("candidate_id", candidate["candidate_id"]), ("experiment_id", spec["experiment_id"])):
        if validated[key] != expected:
            raise ValueError(f"executor_result_{key}_mismatch")
    return validated
