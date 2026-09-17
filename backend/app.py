from __future__ import annotations

import hmac
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import ValidationError

from experiment.case_registry import CaseRegistry, CaseRegistryError
from experiment.evaluation_contract import compile_live_acceptance
from experiment.executor_base import (
    ExecutorAuthenticationError,
    ExecutorResponseError,
    ExecutorTimeoutError,
    LiveExecutionUnavailable,
)
from experiment.pipeline import run_multi_candidate_pipeline
from .adapters.yuanqi import YuanqiMappingError, prepare_run_requests
from .live_executor import ExternalApiLiveExecutor, PassthroughWorkflowResultAdapter, YuanqiLiveExecutor
from .schemas import RunAccepted, RunRequest, RunStatusResponse

app = FastAPI(title="AI POC实验执行后端", version="1.2.3")
RUN_STORE: dict[str, dict[str, Any]] = {}
_STORE_LOCK = threading.RLock()
_EXECUTOR = ThreadPoolExecutor(max_workers=max(2, int(os.getenv("MVP_WORKER_THREADS", "4"))))


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="server_api_key_not_configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_api_key")
    supplied = authorization[7:]
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid_api_key")


def get_case_registry() -> CaseRegistry:
    return CaseRegistry()


def get_live_executor():
    kind = os.getenv("LIVE_EXECUTOR_KIND", "YUANQI").strip().upper()
    if kind == "YUANQI":
        return YuanqiLiveExecutor.from_env()
    if kind == "EXTERNAL_PASSTHROUGH":
        endpoint = os.getenv("LIVE_EXECUTOR_URL", "").strip()
        key = os.getenv("LIVE_EXECUTOR_API_KEY")
        timeout = float(os.getenv("LIVE_EXECUTOR_TIMEOUT_SECONDS", "20"))
        if not endpoint:
            raise LiveExecutionUnavailable("LIVE_EXECUTOR_URL未配置。")
        return ExternalApiLiveExecutor(endpoint=endpoint, api_key=key, response_adapter=PassthroughWorkflowResultAdapter(), timeout_seconds=timeout)
    raise LiveExecutionUnavailable(f"unsupported_live_executor_kind:{kind}")


def _set_record(run_id: str, **changes: Any) -> None:
    with _STORE_LOCK:
        if run_id not in RUN_STORE:
            return
        RUN_STORE[run_id].update(changes)


def _build_evaluation_contract(task: Mapping[str, Any], run_context: Mapping[str, Any]) -> dict[str, Any]:
    mode = run_context["mode"]
    if mode == "BENCHMARK":
        registry = get_case_registry()
        registry.validate_public_task(dict(task))
        return registry.build_evaluation_contract(str(task["case_id"]))
    if mode == "LIVE_POC":
        return compile_live_acceptance(str(task["case_id"]), dict(run_context["live_acceptance_contract"] or {}))
    raise ValueError(f"unsupported_run_context_mode:{mode}")


def _execute_run(run_id: str, task: dict[str, Any], candidates: list[dict[str, Any]], specs: list[dict[str, Any]], run_context: dict[str, Any]) -> None:
    _set_record(run_id, status="RUNNING")
    try:
        contract = _build_evaluation_contract(task, run_context)
        if any(s["execution_mode"] == "LIVE" for s in specs):
            if os.getenv("EXECUTOR_MODE", "FIXTURE").strip().upper() != "LIVE":
                raise LiveExecutionUnavailable("live_execution_disabled_by_config")
            live_executor = get_live_executor()
        else:
            live_executor = None

        record = run_multi_candidate_pipeline(
            task,
            candidates,
            specs,
            evaluation_contract=contract,
            master_run_id=run_id,
            live_executor=live_executor,
            comparison_rules=run_context.get("comparison_rules"),
        )
        first_workflow = first_eval = first_decision = None
        if len(record["candidate_results"]) == 1 and len(record["candidate_results"][0]["repeats"]) == 1:
            first = record["candidate_results"][0]["repeats"][0]
            first_workflow = first["workflow_result"]
            first_eval = first["evaluation_result"]
            first_decision = first["decision_card"]
        _set_record(
            run_id,
            status="COMPLETED",
            candidate_results=record["candidate_results"],
            comparison_result=record["comparison_result"],
            workflow_result=first_workflow,
            evaluation_result=first_eval,
            decision_card=first_decision,
            evaluation_contract_source=contract["source"],
            error=None,
        )
    except Exception as exc:  # 任务层失败写入FAILED，由GET暴露；POST已快速202返回。
        if isinstance(exc, (CaseRegistryError, ValueError, ExecutorAuthenticationError, ExecutorTimeoutError, ExecutorResponseError, LiveExecutionUnavailable)):
            code = exc.__class__.__name__
        else:
            code = "UnhandledRunError"
        _set_record(run_id, status="FAILED", error={"code": code, "message": str(exc)})


def _submit_run(request: RunRequest) -> RunAccepted:
    run_id = f"run-{uuid4().hex[:12]}"
    task, candidates, specs, run_context = request.normalized()
    if any(s["case_id"] != task["case_id"] for s in specs) or any(c["case_id"] != task["case_id"] for c in candidates):
        raise HTTPException(status_code=422, detail="case_id_mismatch_in_request")

    # Benchmark的未知case与case-id借壳在提交时就拒绝；LIVE_POC动态Case不走Registry。
    if run_context["mode"] == "BENCHMARK":
        try:
            registry = get_case_registry()
            registry.validate_public_task(task)
            registry.get_private_gold(task["case_id"])
        except CaseRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    elif run_context["mode"] == "LIVE_POC":
        try:
            # 提交时即冻结并校验实质Acceptance，避免“只有notes”先排队后再给漂亮结论。
            compile_live_acceptance(str(task["case_id"]), dict(run_context.get("live_acceptance_contract") or {}))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    initial = {
        "run_id": run_id,
        "status": "QUEUED",
        "case_id": task["case_id"],
        "run_context_mode": run_context["mode"],
        "evaluation_contract_source": None,
        "candidate_results": None,
        "comparison_result": None,
        "workflow_result": None,
        "evaluation_result": None,
        "decision_card": None,
        "error": None,
    }
    with _STORE_LOCK:
        RUN_STORE[run_id] = initial
    _EXECUTOR.submit(_execute_run, run_id, task, candidates, specs, run_context)
    return RunAccepted(run_id=run_id, status="QUEUED", result_url=f"/api/v1/runs/{run_id}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "sandbox-or-local-mvp", "version": "1.2.3"}


@app.post("/api/v1/runs", response_model=RunAccepted, status_code=202, dependencies=[Depends(require_api_key)])
def create_run(request: RunRequest) -> RunAccepted:
    """平台无关异步提交入口：202 + run_id，GET轮询状态。"""
    return _submit_run(request)


@app.post("/api/v1/yuanqi/runs", response_model=RunAccepted, status_code=202, dependencies=[Depends(require_api_key)])
def create_yuanqi_run(payload: dict[str, Any]) -> RunAccepted:
    """腾讯元器前半段专用入口：原始payload → Adapter → 平台无关RunRequest → 核心Pipeline。"""
    try:
        internal = prepare_run_requests(payload)
        request = RunRequest.model_validate(internal)
    except (YuanqiMappingError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"yuanqi_payload_invalid:{exc}") from exc
    return _submit_run(request)


@app.get("/api/v1/runs/{run_id}", response_model=RunStatusResponse, dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> RunStatusResponse:
    with _STORE_LOCK:
        result = dict(RUN_STORE.get(run_id) or {})
    if not result:
        raise HTTPException(status_code=404, detail="run_not_found")
    return RunStatusResponse(**result)
