from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import httpx

from experiment.executor_base import (
    ExecutorAuthenticationError,
    ExecutorResponseError,
    ExecutorTimeoutError,
    ExperimentExecutor,
    LiveExecutionUnavailable,
)
from experiment.schemas import validate_workflow_result
from .adapters.yuanqi import YuanqiResponseAdapter, YuanqiResponseMapping


class ResponseAdapter(Protocol):
    def parse(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class PassthroughWorkflowResultAdapter:
    """仅用于受控测试或上游已经输出平台无关workflow_result的场景。"""
    def parse(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return validate_workflow_result(payload)


@dataclass
class ExternalApiLiveExecutor(ExperimentExecutor):
    endpoint: str
    api_key: str | None
    response_adapter: ResponseAdapter
    timeout_seconds: float = 20.0
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    client: httpx.Client | None = None

    def execute(self, *, task: Mapping[str, Any], candidate: Mapping[str, Any], experiment_spec: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        if not self.endpoint:
            raise LiveExecutionUnavailable("LIVE_EXECUTOR_URL未配置。")
        if not self.api_key:
            raise ExecutorAuthenticationError("LIVE执行器鉴权密钥缺失。")
        headers = {"Content-Type": "application/json", self.auth_header: f"{self.auth_prefix} {self.api_key}".strip()}
        payload = {"run_id": run_id, "task": dict(task), "candidate": dict(candidate), "experiment_spec": dict(experiment_spec)}
        close_after = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            try:
                response = client.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout_seconds)
            except httpx.TimeoutException as exc:
                raise ExecutorTimeoutError("LIVE执行器HTTP请求超时。") from exc
            except httpx.HTTPError as exc:
                raise LiveExecutionUnavailable(f"LIVE执行器网络错误:{exc.__class__.__name__}") from exc
            if response.status_code in {401, 403}:
                raise ExecutorAuthenticationError(f"LIVE执行器鉴权失败:HTTP_{response.status_code}")
            if response.status_code >= 400:
                raise LiveExecutionUnavailable(f"LIVE执行器HTTP错误:{response.status_code}")
            try:
                raw = response.json()
            except Exception as exc:
                raise ExecutorResponseError("LIVE执行器返回非法JSON。") from exc
            if not isinstance(raw, Mapping):
                raise ExecutorResponseError("LIVE执行器JSON顶层必须为对象。")
            try:
                if hasattr(self.response_adapter, "parse_with_context"):
                    parsed = self.response_adapter.parse_with_context(raw, task=task, candidate=candidate, experiment_spec=experiment_spec, run_id=run_id, source_endpoint=self.endpoint)
                else:
                    parsed = self.response_adapter.parse(raw)
            except Exception as exc:
                raise ExecutorResponseError(f"LIVE响应解析失败:{exc}") from exc
            return validate_workflow_result(parsed)
        finally:
            if close_after:
                client.close()


class YuanqiLiveExecutor(ExternalApiLiveExecutor):
    """腾讯元器LIVE执行器骨架。真实字段映射必须通过配置文件由联调结果提供。"""

    @classmethod
    def from_env(cls, *, client: httpx.Client | None = None) -> "YuanqiLiveExecutor":
        endpoint = os.getenv("YUANQI_EXECUTOR_URL", "").strip()
        api_key = os.getenv("YUANQI_EXECUTOR_API_KEY")
        mapping_file = os.getenv("YUANQI_RESPONSE_MAPPING_FILE", "").strip()
        if not endpoint:
            raise LiveExecutionUnavailable("YUANQI_EXECUTOR_URL未配置。")
        if not mapping_file:
            raise LiveExecutionUnavailable("YUANQI_RESPONSE_MAPPING_FILE未配置；不得猜测腾讯元器真实返回结构。")
        path = Path(mapping_file)
        if not path.exists():
            raise LiveExecutionUnavailable("YUANQI_RESPONSE_MAPPING_FILE不存在。")
        try:
            mapping_payload = json.loads(path.read_text(encoding="utf-8"))
            mapping = YuanqiResponseMapping(workflow_result_path=mapping_payload.get("workflow_result_path"), paths=dict(mapping_payload.get("paths") or {}), provider=str(mapping_payload.get("provider") or "Tencent Yuanqi"))
        except Exception as exc:
            raise LiveExecutionUnavailable(f"腾讯元器响应映射配置无效:{exc}") from exc
        timeout = float(os.getenv("YUANQI_EXECUTOR_TIMEOUT_SECONDS", "20"))
        return cls(endpoint=endpoint, api_key=api_key, response_adapter=YuanqiResponseAdapter(mapping), timeout_seconds=timeout, client=client)
