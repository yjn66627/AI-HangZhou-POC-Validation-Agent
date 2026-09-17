from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from backend.app import app as inner_app

ASGIScope = MutableMapping[str, Any]
ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]


class YuanqiTransportWrapper:
    """腾讯元器 Transport 兼容层。

    仅负责将 ``{"payload_json": "<JSON object string>"}`` 解包为原始 JSON object，
    然后把请求交给既有 FastAPI 应用。业务校验、API Key 鉴权、Adapter、RunRequest、
    Evaluator、Decision Engine 与 Comparison 均仍由被冻结的 inner app 负责。
    """

    TARGET_PATH = "/api/v1/yuanqi/runs"

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.inner_app = app

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") != self.TARGET_PATH:
            await self.inner_app(scope, receive, send)
            return

        body = await self._read_body(receive)
        normalized = self._normalize_if_transport_envelope(body)
        if normalized is None:
            # Legacy直接object或由inner app自行处理的无效JSON：原字节透传。
            await self.inner_app(scope, self._single_body_receive(body), send)
            return
        if isinstance(normalized, _TransportError):
            await self._send_error(send, normalized.detail)
            return

        new_scope = dict(scope)
        new_scope["headers"] = self._headers_with_content_length(scope.get("headers", []), len(normalized))
        await self.inner_app(new_scope, self._single_body_receive(normalized), send)

    @staticmethod
    async def _read_body(receive: ASGIReceive) -> bytes:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                break
            if message.get("type") != "http.request":
                continue
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        return b"".join(chunks)

    @staticmethod
    def _single_body_receive(body: bytes) -> ASGIReceive:
        sent = False

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        return receive

    @classmethod
    def _normalize_if_transport_envelope(cls, body: bytes) -> bytes | "_TransportError" | None:
        try:
            outer = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 非法legacy body保持原行为，由FastAPI/Pydantic处理。
            return None

        if not isinstance(outer, dict) or "payload_json" not in outer:
            return None

        # fail-closed：Transport envelope不得与任何额外字段并存，避免静默合并/覆盖业务语义。
        if set(outer) != {"payload_json"}:
            return _TransportError("payload_json_conflicts_with_outer_fields")

        payload_json = outer.get("payload_json")
        if not isinstance(payload_json, str):
            return _TransportError("payload_json_must_be_string")
        if not payload_json.strip():
            return _TransportError("payload_json_must_not_be_empty")

        try:
            inner = json.loads(payload_json)
        except json.JSONDecodeError:
            return _TransportError("payload_json_malformed_json")

        if not isinstance(inner, dict):
            return _TransportError("payload_json_root_must_be_object")

        return json.dumps(inner, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _headers_with_content_length(headers: list[tuple[bytes, bytes]], body_length: int) -> list[tuple[bytes, bytes]]:
        # 除 Content-Length 外原样保留所有Header，包括Authorization。
        kept = [(k, v) for (k, v) in headers if k.lower() != b"content-length"]
        kept.append((b"content-length", str(body_length).encode("ascii")))
        return kept

    @staticmethod
    async def _send_error(send: ASGISend, detail: str) -> None:
        body = json.dumps({"detail": f"yuanqi_transport_invalid:{detail}"}, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 422,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


class _TransportError:
    def __init__(self, detail: str):
        self.detail = detail


app = YuanqiTransportWrapper(inner_app)
