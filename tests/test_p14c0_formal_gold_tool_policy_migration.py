from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from experiment.case_registry import CaseRegistry

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
MIGRATED_CASE_IDS = ["TEST-R2", "TEST-R3", "TEST-I2", "TEST-A2", "TEST-V2"]
ZERO_TOOL_CASE_ID = "TEST-P1"

PUBLIC_DATASET_SHA256 = "8f284de6e7def135b11abb37fb87ae211a4d2eb00d296f5ba333349db91635de"
CASE_REGISTRY_SHA256 = "00eb6489116db85ffe87e40b2d7a10ad4e9217d5cbe24f9d8cd968954bb0199d"
COMPILER_SHA256 = "8ace786de1e0be40f40bf74c087e65e1a374ede3966a333cd6eeabd65249bd22"
TEST_P1_GOLD_CANONICAL_SHA256 = "17ff7e7f0bc02cb5402defe9f43800379cf117a93b3a1d712447ebd93c827866"

PRE_GOLD_WITHOUT_ALLOWED_TOOLS_SHA256 = {
    "TEST-R2": "581e39ddcc885c3882b3bd4b3e009650db78b5440a9d2504ca1ccbc0b50ae6e0",
    "TEST-R3": "826085c0a908b7282addfe37a4b68a08d7f465672ce75fd1576022fcf1a530e4",
    "TEST-I2": "8aac193602e0ca189a82924db5cc64fca7b2a88072541083c883b482498c8d07",
    "TEST-A2": "41ec879b0f7f1b8f8a9c96b1e79197f4ff4b24c7bf94eb26e0986f1a94f88f8f",
    "TEST-V2": "570e76ed8ea656b507be53da36efb7cf779d53f82892085b6f304dd1195b61ed",
}

EXPECTED_GOLD_SEMANTICS = {
    "TEST-R2": (True, True, True, []),
    "TEST-R3": (True, False, True, []),
    "TEST-I2": (True, True, True, []),
    "TEST-A2": (True, True, True, []),
    "TEST-V2": (True, True, True, []),
}


def _load(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _map(name: str) -> dict[str, dict]:
    return {row["case_id"]: row for row in _load(name)["cases"]}


def test_public_formal_dataset_remains_byte_identical():
    assert hashlib.sha256((DATASETS / "formal_test_inputs.json").read_bytes()).hexdigest() == PUBLIC_DATASET_SHA256


def test_registry_and_private_gold_compiler_remain_byte_identical():
    assert hashlib.sha256((ROOT / "experiment" / "case_registry.py").read_bytes()).hexdigest() == CASE_REGISTRY_SHA256
    assert hashlib.sha256((ROOT / "experiment" / "evaluation_contract.py").read_bytes()).hexdigest() == COMPILER_SHA256


def test_migrated_private_gold_allowed_tools_exactly_match_public_authority():
    public = _map("formal_test_inputs.json")
    gold = _map("formal_test_gold_private.json")
    for case_id in MIGRATED_CASE_IDS:
        assert gold[case_id]["expected"]["allowed_tools"] == public[case_id]["allowed_tools"]
        assert gold[case_id]["expected"]["allowed_tools"]


def test_migration_preserves_formal_tool_names_verbatim():
    public = _map("formal_test_inputs.json")
    gold = _map("formal_test_gold_private.json")
    for case_id in MIGRATED_CASE_IDS:
        assert len(gold[case_id]["expected"]["allowed_tools"]) == len(public[case_id]["allowed_tools"])
        for actual, authority in zip(gold[case_id]["expected"]["allowed_tools"], public[case_id]["allowed_tools"]):
            assert actual == authority


def test_required_tools_are_not_expanded_by_allowed_tools_migration():
    gold = _map("formal_test_gold_private.json")
    for case_id in MIGRATED_CASE_IDS + [ZERO_TOOL_CASE_ID]:
        assert gold[case_id]["expected"]["required_tools"] == []


def test_other_private_gold_semantics_are_unchanged_for_migrated_cases():
    gold = _map("formal_test_gold_private.json")
    for case_id in MIGRATED_CASE_IDS:
        row = copy.deepcopy(gold[case_id])
        row["expected"] = copy.deepcopy(row["expected"])
        row["expected"].pop("allowed_tools", None)
        assert _canonical_sha(row) == PRE_GOLD_WITHOUT_ALLOWED_TOOLS_SHA256[case_id]


def test_evidence_root_cause_and_escalation_semantics_are_unchanged():
    gold = _map("formal_test_gold_private.json")
    for case_id, (evidence_required, should_escalate, root_cause_must_be_evidenced, required_tools) in EXPECTED_GOLD_SEMANTICS.items():
        expected = gold[case_id]["expected"]
        assert expected["evidence_required"] is evidence_required
        assert expected["should_escalate"] is should_escalate
        assert expected["root_cause_must_be_evidenced"] is root_cause_must_be_evidenced
        assert expected["required_tools"] == required_tools


def test_test_p1_none_allowed_preserved():
    public = _map("formal_test_inputs.json")[ZERO_TOOL_CASE_ID]
    gold = _map("formal_test_gold_private.json")[ZERO_TOOL_CASE_ID]
    assert public["allowed_tools"] == []
    assert gold["expected"]["allowed_tools"] == []
    assert gold["expected"]["required_tools"] == []
    assert _canonical_sha(gold) == TEST_P1_GOLD_CANONICAL_SHA256


def test_compiler_emits_allowlist_for_migrated_cases_and_none_allowed_for_test_p1():
    registry = CaseRegistry()
    public = _map("formal_test_inputs.json")
    for case_id in MIGRATED_CASE_IDS:
        contract = registry.build_evaluation_contract(case_id)
        assert contract["tool_policy_mode"] == "ALLOWLIST"
        assert contract["allowed_tools"] == public[case_id]["allowed_tools"]
        assert contract["required_tools"] == []
    p1 = registry.build_evaluation_contract(ZERO_TOOL_CASE_ID)
    assert p1["tool_policy_mode"] == "NONE_ALLOWED"
    assert p1["allowed_tools"] == []
    assert p1["required_tools"] == []


def test_formal_public_private_case_ids_and_required_shapes_remain_valid():
    public = _load("formal_test_inputs.json")
    gold = _load("formal_test_gold_private.json")
    public_ids = [row["case_id"] for row in public["cases"]]
    gold_ids = [row["case_id"] for row in gold["cases"]]
    assert public_ids == gold_ids
    assert set(public_ids) == set(MIGRATED_CASE_IDS + [ZERO_TOOL_CASE_ID])
    for row in gold["cases"]:
        expected = row["expected"]
        for key in (
            "allowed_actions",
            "required_tools",
            "allowed_tools",
            "forbidden_tools",
            "evidence_required",
            "should_escalate",
            "guardrail_required",
            "root_cause_must_be_evidenced",
        ):
            assert key in expected


def test_all_private_gold_cases_compile_to_valid_evaluation_contracts():
    registry = CaseRegistry()
    for case_id in MIGRATED_CASE_IDS + [ZERO_TOOL_CASE_ID]:
        contract = registry.build_evaluation_contract(case_id)
        assert contract["case_id"] == case_id
        assert contract["source"] == "PRIVATE_GOLD"


def test_fixture_assets_remain_unchanged_by_formal_gold_migration():
    assert hashlib.sha256((DATASETS / "fixture_inputs.json").read_bytes()).hexdigest() == "cd7a27df1612008d8ec4da70cdb4880600a5ea740bad6f61560fb8c53986adab"
    assert hashlib.sha256((DATASETS / "fixture_gold_private.json").read_bytes()).hexdigest() == "c971b43195ac473672ecba4cb4725166a4edaa577c5a36f39293abc0d4545e71"
