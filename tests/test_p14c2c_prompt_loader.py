from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from executor_gateway import prompt_loader
from executor_gateway.config import (
    APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH,
    APPROVED_TOOL_ENABLED_PROMPT_SHA256,
    APPROVED_TOOL_ENABLED_PROMPT_VERSION,
    GatewayConfigurationError,
    ToolEnabledPromptCandidateConfig,
)
from executor_gateway.prompt_loader import PromptCandidateLoadError, load_tool_enabled_prompt


APPROVED_ASSET = (
    Path(__file__).resolve().parents[1]
    / "executor_gateway"
    / "prompt_assets"
    / "EXECUTOR_AGENT_SYSTEM_PROMPT_C2_TOOL_ENABLED_CANDIDATE_r1.md"
)
APPROVED_BYTES = APPROVED_ASSET.read_bytes()


def enabled_config() -> ToolEnabledPromptCandidateConfig:
    return ToolEnabledPromptCandidateConfig(enabled=True)


def make_repo(tmp_path: Path, payload: bytes | None = APPROVED_BYTES) -> Path:
    root = tmp_path / "repo"
    target = root.joinpath(*APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        target.write_bytes(payload)
    return root


def point_loader_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(prompt_loader, "_repository_root", lambda: root)


def test_gate_disabled_by_default_and_loader_fails_closed() -> None:
    cfg = ToolEnabledPromptCandidateConfig.from_environ({})
    assert cfg.enabled is False
    with pytest.raises(PromptCandidateLoadError, match="tool_enabled_prompt_gate_disabled"):
        load_tool_enabled_prompt(cfg)


def test_exact_approved_candidate_loads_and_metadata_is_bound() -> None:
    cfg = enabled_config()
    loaded = load_tool_enabled_prompt(cfg)
    assert loaded.text == APPROVED_BYTES.decode("utf-8")
    assert loaded.version == APPROVED_TOOL_ENABLED_PROMPT_VERSION
    assert loaded.sha256 == APPROVED_TOOL_ENABLED_PROMPT_SHA256
    assert loaded.logical_path == APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH


def test_candidate_asset_bytes_are_exact_controller_approved_sha() -> None:
    assert hashlib.sha256(APPROVED_BYTES).hexdigest() == APPROVED_TOOL_ENABLED_PROMPT_SHA256


def test_approved_environment_binding_enables_only_exact_candidate() -> None:
    cfg = ToolEnabledPromptCandidateConfig.from_environ(
        {
            "EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true",
            "EXECUTOR_TOOL_ENABLED_PROMPT_VERSION": APPROVED_TOOL_ENABLED_PROMPT_VERSION,
            "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH,
            "EXECUTOR_TOOL_ENABLED_PROMPT_SHA256": APPROVED_TOOL_ENABLED_PROMPT_SHA256,
        }
    )
    assert cfg.enabled is True
    assert cfg.version == APPROVED_TOOL_ENABLED_PROMPT_VERSION
    assert cfg.logical_path == APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH
    assert cfg.expected_sha256 == APPROVED_TOOL_ENABLED_PROMPT_SHA256


@pytest.mark.parametrize(
    "env",
    [
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_VERSION": "r2"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_SHA256": "0" * 64},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "other.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "/tmp/prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "../prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "C:\\temp\\prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "C:temp\\prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "\\\\server\\share\\prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "https://example.com/prompt.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "true", "EXECUTOR_TOOL_ENABLED_PROMPT_LOGICAL_PATH": "executor_gateway/EXECUTOR_AGENT_SYSTEM_PROMPT.md"},
        {"EXECUTOR_TOOL_ENABLED_PROMPT_ENABLED": "maybe"},
    ],
)
def test_unapproved_or_unsafe_config_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(GatewayConfigurationError):
        ToolEnabledPromptCandidateConfig.from_environ(env)


def test_candidate_missing_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = make_repo(tmp_path, payload=None)
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_missing"):
        load_tool_enabled_prompt(enabled_config())


def test_one_byte_mutation_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mutated = bytearray(APPROVED_BYTES)
    mutated[-1] ^= 1
    root = make_repo(tmp_path, bytes(mutated))
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_sha256_mismatch"):
        load_tool_enabled_prompt(enabled_config())


def test_directory_target_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root.joinpath(*APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH.split("/"))
    target.mkdir(parents=True)
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_not_regular_file"):
        load_tool_enabled_prompt(enabled_config())


def test_invalid_utf8_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = make_repo(tmp_path, b"\xff\xfe\xfd")
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_invalid_utf8"):
        load_tool_enabled_prompt(enabled_config())


def test_utf8_bom_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = make_repo(tmp_path, b"\xef\xbb\xbf" + APPROVED_BYTES)
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_utf8_bom_forbidden"):
        load_tool_enabled_prompt(enabled_config())


def test_empty_prompt_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = make_repo(tmp_path, b"")
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_empty"):
        load_tool_enabled_prompt(enabled_config())


def test_symlink_target_is_forbidden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root.joinpath(*APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH.split("/"))
    target.parent.mkdir(parents=True)
    outside = tmp_path / "approved-copy.md"
    outside.write_bytes(APPROVED_BYTES)
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation not supported")
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_symlink_forbidden"):
        load_tool_enabled_prompt(enabled_config())


def test_no_fallback_to_legacy_prompt_when_candidate_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_repo(tmp_path, payload=None)
    legacy = root / "executor_gateway" / "EXECUTOR_AGENT_SYSTEM_PROMPT.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy prompt must not be returned", encoding="utf-8")
    point_loader_at(monkeypatch, root)
    with pytest.raises(PromptCandidateLoadError, match="prompt_candidate_missing"):
        load_tool_enabled_prompt(enabled_config())


def test_safe_summary_exposes_no_local_absolute_path() -> None:
    summary = enabled_config().safe_summary()
    assert summary["fallback_allowed"] is False
    assert summary["logical_path"] == APPROVED_TOOL_ENABLED_PROMPT_LOGICAL_PATH
    assert not str(summary["logical_path"]).startswith(("/", "\\"))
