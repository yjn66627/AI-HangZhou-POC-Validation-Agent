from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_agent_llm(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_LLM_URL", raising=False)
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def success_bundle() -> dict:
    return json.loads((ROOT / "examples" / "fx-success_bundle.json").read_text(encoding="utf-8"))


@pytest.fixture
def api_headers(monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("EXECUTOR_MODE", "FIXTURE")
    return {"Authorization": "Bearer test-api-key"}


@pytest.fixture
def three_candidate_payload(success_bundle: dict) -> dict:
    base = deepcopy(success_bundle)
    task = base["task"]
    candidates = []
    specs = []
    profiles = ["NORMAL_SUCCESS", "QUALITY_LOW", "METRICS_MISSING"]
    for i, profile in enumerate(profiles, start=1):
        c = deepcopy(base["candidate"])
        c["candidate_id"] = f"cand-compare-{i}"
        c["name"] = f"候选{i}"
        s = deepcopy(base["experiment_spec"])
        s["candidate_id"] = c["candidate_id"]
        s["experiment_id"] = f"exp-compare-{i}"
        s["simulation"]["profile"] = profile
        candidates.append(c); specs.append(s)
    return {"task": task, "candidates": candidates, "experiment_specs": specs}
