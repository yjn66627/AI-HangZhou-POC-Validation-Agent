from __future__ import annotations

import json
from pathlib import Path

from experiment.case_registry import CaseRegistry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_INPUTS = ROOT / "datasets" / "formal_test_inputs.json"


def test_default_registry_loads_public_inputs_without_extra_mount(monkeypatch):
    monkeypatch.delenv("CASE_REGISTRY_PATH", raising=False)
    registry = CaseRegistry(public_files=[PUBLIC_INPUTS])
    public = registry.get_public_input("TEST-P1")

    assert public["case_id"] == "TEST-P1"
    assert public["allowed_tools"] == []
    assert registry.case_ids() == {row["case_id"] for row in json.loads(PUBLIC_INPUTS.read_text(encoding="utf-8"))["cases"]}


def test_explicit_registry_path_loads_a_custom_dataset(monkeypatch):
    monkeypatch.setenv("CASE_REGISTRY_PATH", str(PUBLIC_INPUTS))
    registry = CaseRegistry(public_files=[PUBLIC_INPUTS])
    loaded = registry.get_private_gold("TEST-P1")

    assert loaded["case_id"] == "TEST-P1"
    assert loaded["allowed_tools"] == []
