from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.evaluation_contract import compile_live_acceptance


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_INPUTS = ROOT / "datasets" / "formal_test_inputs.json"


def _acceptance_payload(*, allowed_tools: list[str] | None, required_tools: list[str] | None = None) -> dict:
    payload = {
        "case_id": "PUBLIC-TOOLS",
        "evidence_required": True,
        "should_escalate": False,
        "guardrail_required": True,
        "allowed_tools": allowed_tools,
        "decision_criteria": {
            "source": "USER_CONFIRMED",
            "quality": {"status": "REQUIRED", "min_score": 0.92},
            "cost": {"status": "NOT_APPLICABLE"},
            "latency": {"status": "NOT_APPLICABLE"},
        },
    }
    if required_tools is not None:
        payload["required_tools"] = required_tools
    return payload


def test_public_formal_inputs_have_explicit_tool_policy_shape():
    data = json.loads(PUBLIC_INPUTS.read_text(encoding="utf-8"))
    cases = data["cases"]

    assert data["usage"] == "EXECUTOR_VISIBLE_FORMAL_INPUT"
    assert cases
    for case in cases:
        assert isinstance(case["case_id"], str) and case["case_id"]
        assert isinstance(case["user_query"], str) and case["user_query"]
        assert isinstance(case["allowed_tools"], list)

    zero_tool_case = next(case for case in cases if case["case_id"] == "TEST-P1")
    assert zero_tool_case["allowed_tools"] == []


@pytest.mark.parametrize(
    ("allowed_tools", "expected_mode", "expected_tools"),
    [
        (None, "UNRESTRICTED", []),
        ([], "NONE_ALLOWED", []),
        (["read_public_input"], "ALLOWLIST", ["read_public_input"]),
    ],
)
def test_public_acceptance_contract_distinguishes_tool_policy_modes(
    allowed_tools: list[str] | None, expected_mode: str, expected_tools: list[str]
):
    contract = compile_live_acceptance("PUBLIC-TOOLS", _acceptance_payload(allowed_tools=allowed_tools))

    assert contract["source"] == "LIVE_ACCEPTANCE_CONTRACT"
    assert contract["tool_policy_mode"] == expected_mode
    assert contract["allowed_tools"] == expected_tools
    assert contract["required_tools"] == []


def test_public_acceptance_contract_preserves_explicit_required_tools():
    contract = compile_live_acceptance(
        "PUBLIC-TOOLS",
        _acceptance_payload(allowed_tools=["read_public_input"], required_tools=["read_public_input"]),
    )

    assert contract["required_tools"] == ["read_public_input"]
    assert contract["allowed_tools"] == ["read_public_input"]
    assert contract["tool_policy_mode"] == "ALLOWLIST"


@pytest.mark.parametrize("field", ["demo_default", "template_only"])
def test_public_acceptance_contract_rejects_unverified_defaults(field: str):
    payload = _acceptance_payload(allowed_tools=[])
    payload[field] = True

    with pytest.raises(ValueError, match="demo_default_not_allowed_for_live_decision"):
        compile_live_acceptance("PUBLIC-TOOLS", payload)
