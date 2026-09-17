from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .compatibility import load_agent_contract_validator, parse_executor_agent_json_strict


# Implementation provenance only. These anchors bind this implementation mirror to
# the frozen C2-A-r1 authority; they do not create a second contract authority.
C2_A_R1_PROTOCOL_AUTHORITY_ZIP_SHA256 = (
    "d3bfba07b590c68fccb1758f086f8b63e74b85240a40275dd417a2919c1f625e"
)
C2_A_R1_MODEL_RESPONSE_SCHEMA_ENTRY = "P1.4-C2-A-r1_MODEL_RESPONSE_SCHEMA.json"
C2_A_R1_MODEL_RESPONSE_SCHEMA_ENTRY_SHA256 = (
    "4a8f3f007c250940481cfb1894054096293f2ea0ecd8a863b715d0ed19f9ee70"
)


MODEL_TOOL_REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["turn_type", "requested_tool", "arguments"],
    "properties": {
        "turn_type": {"const": "TOOL_REQUEST"},
        "requested_tool": {"type": "string", "minLength": 1, "maxLength": 128},
        "arguments": {"type": "object"},
    },
}
Draft202012Validator.check_schema(MODEL_TOOL_REQUEST_SCHEMA)
_MODEL_TOOL_REQUEST_VALIDATOR = Draft202012Validator(MODEL_TOOL_REQUEST_SCHEMA)


class ModelToolRequest(BaseModel):
    """Model-visible TOOL_REQUEST branch. Runtime authority fields are forbidden."""

    model_config = ConfigDict(extra="forbid")
    turn_type: str = "TOOL_REQUEST"
    requested_tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]

    @field_validator("turn_type")
    @classmethod
    def _tool_request_only(cls, value: str) -> str:
        if value != "TOOL_REQUEST":
            raise ValueError("turn_type_must_be_TOOL_REQUEST")
        return value


@dataclass(frozen=True)
class ParsedToolRequest:
    request: ModelToolRequest
    raw: dict[str, Any]


@dataclass(frozen=True)
class ParsedFinal:
    semantic: dict[str, Any]


@dataclass(frozen=True)
class ParseError:
    code: str
    detail: str


ParsedModelTurn = ParsedToolRequest | ParsedFinal | ParseError


def _first_error(validator: Draft202012Validator, data: Mapping[str, Any]) -> str | None:
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return None
    first = errors[0]
    path = ".".join(str(x) for x in first.absolute_path)
    return f"{path}:{first.message}" if path else first.message


def parse_model_turn(
    content: Any,
    *,
    final_validator: Draft202012Validator | None = None,
) -> ParsedModelTurn:
    """Strict-parse exactly once, then select TOOL_REQUEST or authoritative FINAL.

    Branch ambiguity fails closed even though the current anchored Final schema and
    TOOL_REQUEST schema are structurally disjoint.
    """

    try:
        data = parse_executor_agent_json_strict(content)
    except ValueError as exc:
        return ParseError(code="MODEL_RESPONSE_STRICT_JSON_INVALID", detail=str(exc))

    final_validator = final_validator or load_agent_contract_validator()
    tool_error = _first_error(_MODEL_TOOL_REQUEST_VALIDATOR, data)
    final_error = _first_error(final_validator, data)
    tool_valid = tool_error is None
    final_valid = final_error is None

    if tool_valid and final_valid:
        return ParseError(
            code="MODEL_RESPONSE_UNION_AMBIGUOUS",
            detail="object accepted by both ModelToolRequest and authoritative Final validators",
        )
    if tool_valid:
        # JSON Schema already enforced the exact wire shape; Pydantic provides the
        # typed object used by the Gateway Orchestrator.
        return ParsedToolRequest(request=ModelToolRequest.model_validate(data), raw=dict(data))
    if final_valid:
        return ParsedFinal(semantic=dict(data))
    return ParseError(
        code="MODEL_RESPONSE_UNION_NO_MATCH",
        detail=f"tool={tool_error}; final={final_error}",
    )
