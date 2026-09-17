from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .client import GatewayModelCallResult, YuanqiOpenApiClient
from .config import GatewaySettings


@dataclass(frozen=True)
class ConfiguredYuanqiModelCaller:
    """Bind one Yuanqi client to one validated GatewaySettings instance.

    This adapter is intentionally transparent: one orchestrator model turn maps
    to exactly one ``YuanqiOpenApiClient.call_model_once`` invocation. It does
    not inspect or mutate messages, parse model output, retry, or own Prompt or
    Tool Runtime authority.
    """

    client: YuanqiOpenApiClient
    settings: GatewaySettings

    async def call_model_once(
        self,
        messages: list[Mapping[str, Any]],
    ) -> GatewayModelCallResult:
        return await self.client.call_model_once(messages, self.settings)
