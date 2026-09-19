from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


class HardDeadlineError(RuntimeError):
    pass


class HardDeadlineTimeout(HardDeadlineError):
    def __init__(self, *, worker_pid: int | None = None, termination_method: str | None = None) -> None:
        super().__init__("hard_deadline_timeout")
        self.worker_pid = worker_pid
        self.termination_method = termination_method


class HardDeadlineWorkerError(HardDeadlineError):
    def __init__(self, error_type: str) -> None:
        super().__init__(f"hard_deadline_worker_error:{error_type}")
        self.error_type = error_type


class HardDeadlineResponseTooLarge(HardDeadlineError):
    pass


class HardDeadlineTransportError(HardDeadlineError):
    def __init__(self, error_type: str) -> None:
        super().__init__(f"hard_deadline_transport_error:{error_type}")
        self.error_type = error_type


@dataclass(frozen=True)
class IsolatedWorkerResult:
    value: Any
    elapsed_ms: int


@dataclass(frozen=True)
class HardDeadlineHttpResponse:
    status_code: int
    body: bytes
    content_type: str | None
    elapsed_ms: int


class HardDeadlineTransport(Protocol):
    def get(
        self,
        *,
        url: str,
        bearer_token: str,
        timeout_ms: int,
        max_response_bytes: int,
    ) -> HardDeadlineHttpResponse: ...


def _worker_entry(send_conn: Any, worker: Callable[[Any], Any], payload: Any) -> None:
    try:
        value = worker(payload)
        send_conn.send(("ok", value))
    except BaseException as exc:  # child must convert all failures into a bounded envelope
        try:
            send_conn.send(("error", exc.__class__.__name__))
        except BaseException:
            pass
    finally:
        try:
            send_conn.close()
        except BaseException:
            pass


def _terminate_worker(process: mp.Process) -> str:
    if not process.is_alive():
        process.join(timeout=0)
        return "already_exited"
    process.terminate()
    process.join(timeout=0.25)
    if process.is_alive():
        kill = getattr(process, "kill", None)
        if kill is None:
            process.terminate()
            method = "terminate_retry"
        else:
            kill()
            method = "kill"
        process.join(timeout=0.25)
    else:
        method = "terminate"
    if process.is_alive():
        raise HardDeadlineError("worker_cleanup_failed")
    return method


def run_isolated_worker(
    worker: Callable[[Any], Any],
    payload: Any,
    *,
    timeout_ms: int,
    start_method: str = "spawn",
) -> IsolatedWorkerResult:
    """Run exactly one callable under a parent-owned monotonic wall-clock deadline."""

    if timeout_ms <= 0:
        raise ValueError("timeout_ms_must_be_positive")
    ctx = mp.get_context(start_method)
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    started = time.monotonic()
    deadline = started + (timeout_ms / 1000.0)
    process = ctx.Process(target=_worker_entry, args=(send_conn, worker, payload), daemon=True)
    process.start()
    send_conn.close()

    message: tuple[str, Any] | None = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                method = _terminate_worker(process)
                raise HardDeadlineTimeout(worker_pid=process.pid, termination_method=method)
            if recv_conn.poll(min(remaining, 0.025)):
                try:
                    message = recv_conn.recv()
                except EOFError as exc:
                    raise HardDeadlineWorkerError("WorkerPipeClosed") from exc
                break
            if not process.is_alive():
                if recv_conn.poll(0):
                    try:
                        message = recv_conn.recv()
                    except EOFError as exc:
                        raise HardDeadlineWorkerError("WorkerPipeClosed") from exc
                    break
                raise HardDeadlineWorkerError("WorkerExitedWithoutResult")

        remaining = max(0.0, deadline - time.monotonic())
        process.join(timeout=remaining)
        if process.is_alive():
            _terminate_worker(process)
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        if time.monotonic() > deadline:
            raise HardDeadlineTimeout(worker_pid=process.pid, termination_method="deadline_after_result")
        if not isinstance(message, tuple) or len(message) != 2:
            raise HardDeadlineWorkerError("MalformedWorkerEnvelope")
        kind, value = message
        if kind == "error":
            raise HardDeadlineWorkerError(str(value))
        if kind != "ok":
            raise HardDeadlineWorkerError("UnknownWorkerEnvelope")
        return IsolatedWorkerResult(value=value, elapsed_ms=elapsed_ms)
    finally:
        try:
            recv_conn.close()
        finally:
            if process.is_alive():
                _terminate_worker(process)
            else:
                process.join(timeout=0)


def _remaining_seconds(deadline_monotonic: float) -> float:
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("deadline_expired")
    return remaining


def perform_http_get_once(
    *,
    url: str,
    bearer_token: str,
    deadline_monotonic: float,
    max_response_bytes: int,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Exactly one streaming GET. Optional transport exists only for deterministic offline tests."""

    import httpx

    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes_must_be_positive")
    remaining = _remaining_seconds(deadline_monotonic)
    phase_timeout = max(0.001, remaining)
    timeout = httpx.Timeout(
        timeout=phase_timeout,
        connect=phase_timeout,
        read=phase_timeout,
        write=phase_timeout,
        pool=phase_timeout,
    )
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    started = time.monotonic()
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        with client.stream("GET", url, headers=headers) as response:
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > max_response_bytes:
                        raise HardDeadlineResponseTooLarge("response_too_large")
                except ValueError:
                    pass
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes():
                _remaining_seconds(deadline_monotonic)
                received += len(chunk)
                if received > max_response_bytes:
                    raise HardDeadlineResponseTooLarge("response_too_large")
                chunks.append(chunk)
            return {
                "status_code": int(response.status_code),
                "body": b"".join(chunks),
                "content_type": response.headers.get("content-type"),
                "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
            }


def _http_get_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    return perform_http_get_once(
        url=str(payload["url"]),
        bearer_token=str(payload["bearer_token"]),
        deadline_monotonic=float(payload["deadline_monotonic"]),
        max_response_bytes=int(payload["max_response_bytes"]),
    )


class HardDeadlineHttpTransportImpl:
    """Production-intent transport: one child process, one GET, no redirect, no retry."""

    def __init__(self, *, start_method: str = "spawn") -> None:
        self.start_method = start_method

    def get(
        self,
        *,
        url: str,
        bearer_token: str,
        timeout_ms: int,
        max_response_bytes: int,
    ) -> HardDeadlineHttpResponse:
        started = time.monotonic()
        deadline = started + (timeout_ms / 1000.0)
        try:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            result = run_isolated_worker(
                _http_get_worker,
                {
                    "url": url,
                    "bearer_token": bearer_token,
                    "deadline_monotonic": deadline,
                    "max_response_bytes": max_response_bytes,
                },
                timeout_ms=remaining_ms,
                start_method=self.start_method,
            )
        except HardDeadlineWorkerError as exc:
            if exc.error_type in {
                "TimeoutError",
                "ConnectTimeout",
                "ReadTimeout",
                "WriteTimeout",
                "PoolTimeout",
                "TimeoutException",
            }:
                raise HardDeadlineTimeout() from None
            if exc.error_type == "HardDeadlineResponseTooLarge":
                raise HardDeadlineResponseTooLarge("response_too_large") from None
            raise HardDeadlineTransportError(exc.error_type) from None
        raw = result.value
        if not isinstance(raw, Mapping):
            raise HardDeadlineTransportError("MalformedWorkerResult")
        body = raw.get("body")
        if not isinstance(body, bytes):
            raise HardDeadlineTransportError("MalformedWorkerBody")
        return HardDeadlineHttpResponse(
            status_code=int(raw.get("status_code")),
            body=body,
            content_type=str(raw["content_type"]) if raw.get("content_type") is not None else None,
            elapsed_ms=max(result.elapsed_ms, int(raw.get("elapsed_ms", 0))),
        )
