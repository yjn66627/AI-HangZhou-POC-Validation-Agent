from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from executor_gateway.config import ToolEnabledPromptCandidateConfig


class PromptCandidateLoadError(RuntimeError):
    """Approved tool-enabled Prompt candidate could not be loaded safely."""


@dataclass(frozen=True)
class LoadedPromptCandidate:
    text: str
    version: str
    sha256: str
    logical_path: str


def _repository_root() -> Path:
    # executor_gateway/ lives directly under the repository root.
    return Path(__file__).resolve().parent.parent


def _resolve_repo_local_candidate(root: Path, logical_path: str) -> Path:
    path = PurePosixPath(logical_path)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise PromptCandidateLoadError("prompt_candidate_unsafe_logical_path")
    if not path.parts or any(not part for part in path.parts):
        raise PromptCandidateLoadError("prompt_candidate_unsafe_logical_path")

    root_resolved = root.resolve(strict=True)
    candidate = root_resolved.joinpath(*path.parts)
    if candidate.is_symlink():
        raise PromptCandidateLoadError("prompt_candidate_symlink_forbidden")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PromptCandidateLoadError("prompt_candidate_missing") from exc

    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PromptCandidateLoadError("prompt_candidate_path_escape") from exc

    if not resolved.is_file():
        raise PromptCandidateLoadError("prompt_candidate_not_regular_file")
    return resolved


def load_tool_enabled_prompt(config: ToolEnabledPromptCandidateConfig) -> LoadedPromptCandidate:
    """Load the one approved C1A Prompt asset; never falls back to another Prompt."""
    if not isinstance(config, ToolEnabledPromptCandidateConfig):
        raise PromptCandidateLoadError("prompt_candidate_config_type_invalid")
    if not config.enabled:
        raise PromptCandidateLoadError("tool_enabled_prompt_gate_disabled")

    candidate_path = _resolve_repo_local_candidate(_repository_root(), config.logical_path)
    try:
        raw = candidate_path.read_bytes()
    except OSError as exc:
        raise PromptCandidateLoadError("prompt_candidate_unreadable") from exc

    if not raw:
        raise PromptCandidateLoadError("prompt_candidate_empty")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PromptCandidateLoadError("prompt_candidate_utf8_bom_forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PromptCandidateLoadError("prompt_candidate_invalid_utf8") from exc

    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != config.expected_sha256:
        raise PromptCandidateLoadError("prompt_candidate_sha256_mismatch")

    return LoadedPromptCandidate(
        text=text,
        version=config.version,
        sha256=actual_sha256,
        logical_path=config.logical_path,
    )
