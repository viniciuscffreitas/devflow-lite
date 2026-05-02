"""DevflowPaths — single source of truth for all devflow filesystem paths.

Resolution order (per-call, NOT cached):
  1. DEVFLOW_ROOT env var (absolute path)
  2. Path.home() / ".claude" / "devflow"  (backward-compat default)

Subpaths (state, telemetry, errors_log, ...) derive from root by default, but
each one honors its own DEVFLOW_* env var override for surgical redirection
(used by tests and by MCP server deployments that split data dirs).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _resolve(env_key: str, fallback: Path) -> Path:
    raw = os.environ.get(env_key)
    return Path(raw) if raw else fallback


@dataclass(frozen=True)
class DevflowPaths:
    root: Path
    state: Path
    telemetry: Path
    skills: Path
    instincts: Path
    judge_golden: Path
    judge_forensics: Path
    errors_log: Path
    config_global: Path
    projects: Path
    claude_md: Path
    settings: Path
    learned_skills: Path
    sg_rules: Path
    rules_root: Path

    def ensure_core_dirs(self) -> None:
        """Create state/telemetry/errors_log dirs if missing. Idempotent."""
        for p in (self.state, self.telemetry, self.errors_log):
            p.mkdir(parents=True, exist_ok=True)


def current_paths() -> DevflowPaths:
    """Return a DevflowPaths resolved from env vars at call time.

    Not cached so pytest monkeypatch works. Cost is ~12 os.environ.get() calls —
    negligible compared to any filesystem operation the caller does next.
    """
    root = _resolve("DEVFLOW_ROOT", Path.home() / ".claude" / "devflow")
    claude_home = Path.home() / ".claude"
    return DevflowPaths(
        root=root,
        state=_resolve("DEVFLOW_STATE_DIR", root / "state"),
        telemetry=_resolve("DEVFLOW_TELEMETRY_DIR", root / "telemetry"),
        skills=_resolve("DEVFLOW_SKILLS_DIR", claude_home / "skills"),
        instincts=_resolve("DEVFLOW_INSTINCTS_DIR", root / "instincts"),
        judge_golden=_resolve("DEVFLOW_JUDGE_GOLDEN_DIR", root / "judge" / "golden"),
        judge_forensics=_resolve("DEVFLOW_JUDGE_FORENSICS_DIR", root / "telemetry" / "judge_forensics"),
        errors_log=_resolve("DEVFLOW_ERRORS_LOG_DIR", root / "logs"),
        config_global=_resolve("DEVFLOW_CONFIG_FILE", root / "devflow-config.json"),
        projects=_resolve("DEVFLOW_PROJECTS_DIR", claude_home / "projects"),
        claude_md=_resolve("DEVFLOW_HARNESS_RULES_FILE", claude_home / "CLAUDE.md"),
        settings=_resolve("DEVFLOW_SETTINGS_FILE", claude_home / "settings.json"),
        learned_skills=_resolve("DEVFLOW_LEARNED_SKILLS_DIR", root / "learned-skills"),
        sg_rules=_resolve("DEVFLOW_SG_RULES_DIR", root / "sg-rules"),
        rules_root=_resolve("DEVFLOW_RULES_ROOT_DIR", claude_home / "rules"),
    )
