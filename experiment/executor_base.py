from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class ExecutorError(RuntimeError):
    """统一执行器错误。"""


class LiveExecutionUnavailable(ExecutorError):
    """LIVE执行器未配置或不可用。"""


class ExecutorAuthenticationError(ExecutorError):
    """LIVE执行器缺少或拒绝鉴权。"""


class ExecutorTimeoutError(ExecutorError):
    """LIVE执行器请求超时。"""


class ExecutorResponseError(ExecutorError):
    """LIVE执行器返回无法解析或不符合契约的数据。"""


class ExperimentExecutor(ABC):
    """平台无关实验执行器接口。Gold/Acceptance Rules不得传入execute。"""

    @abstractmethod
    def execute(
        self,
        *,
        task: Mapping[str, Any],
        candidate: Mapping[str, Any],
        experiment_spec: Mapping[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError
