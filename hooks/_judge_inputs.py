"""Judge input builders — helpers that assemble JudgePayload fields.

Extracted from post_task_judge.py to keep that orchestrator under the
600-line file-size cap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _paths import current_paths  # noqa: E402  (sys.path bootstrap above)
from knowledge.governance import RuleEngine, RuleSet  # noqa: E402  (sys.path bootstrap above)

_UNIVERSAL_RULES_PATH = Path.home() / ".claude" / "devflow" / "docs" / "global-rules.md"
_GOLDEN_MAX = 5
_GOLDEN_MAX_BYTES = 3_072  # 3 KB per file — keeps prompt under budget


def _read_spec(state_dir: Path) -> str:
    spec_path = state_dir / "active-spec.json"
    if not spec_path.exists():
        return ""
    try:
        spec = json.loads(spec_path.read_text())
        plan_path = spec.get("plan_path", "")
        if plan_path and not plan_path.startswith("/"):
            candidate = _DEVFLOW_ROOT / plan_path
            if candidate.exists():
                return candidate.read_text()
        return str(plan_path)
    except (json.JSONDecodeError, OSError):
        return ""


def _read_harness_rules(project_root: Path) -> list:
    """Load harness rules from target repo, falling back to global.

    Priority:
      1. <project_root>/PROJECT_WIKI.md
      2. <project_root>/CLAUDE.md
      3. current_paths().claude_md
    """
    candidates = [
        project_root / "PROJECT_WIKI.md",
        project_root / "CLAUDE.md",
        current_paths().claude_md,
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        kept = [line for line in lines if line.strip()][:50]
        if kept:
            return kept
    return []


def _read_existing_code(diff: str) -> str:
    """Read first 100 lines of each file modified in the diff."""
    parts = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            candidate = Path(file_path)
            if not candidate.exists():
                candidate = Path.cwd() / file_path
            if candidate.exists():
                try:
                    content_lines = candidate.read_text().splitlines()[:100]
                    parts.append(f"# {file_path}\n" + "\n".join(content_lines))
                except OSError:
                    pass
    return "\n\n".join(parts)


def _read_feature_path(state_dir: Path) -> str:
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            return profile.get("feature_path") or "."
        except (json.JSONDecodeError, OSError):
            pass
    return "."


def _read_curated_golden_md() -> list:
    """Return up to _GOLDEN_MAX golden .md files (newest by mtime)."""
    golden_dir = current_paths().judge_golden
    if not golden_dir.is_dir():
        return []
    try:
        mds = [p for p in golden_dir.glob("*.md") if p.name.lower() != "readme.md"]
        mds.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for p in mds[:_GOLDEN_MAX]:
            try:
                content = p.read_text()
                if len(content.encode("utf-8")) > _GOLDEN_MAX_BYTES:
                    continue
                out.append(f"<!-- golden: {p.name} -->\n{content}")
            except OSError:
                continue
        return out
    except OSError:
        return []


def _read_jsonl_golden_rows() -> list:
    from telemetry.golden_dataset_reader import read_recent

    paths = current_paths()
    if hasattr(paths, "telemetry_dir"):
        path = paths.telemetry_dir / "golden_dataset.jsonl"
    else:
        path = (
            Path.home() / ".claude" / "devflow" / "telemetry" / "golden_dataset.jsonl"
        )
    rows = read_recent(path, limit=2, max_bytes=_GOLDEN_MAX_BYTES)
    out = []
    for r in rows:
        out.append(
            f"<!-- golden-jsonl: {r.session_id} ({r.language}) -->\n"
            f"Error tail:\n{r.error_log_tail}\n"
            f"Fix diff:\n{(r.fixed_files[0].get('diff') if r.fixed_files else '')}"
        )
    return out


def _read_golden_examples() -> list:
    """Returns golden .md files merged with recent jsonl rows.

    .md examples come from current_paths().judge_golden (curated).
    jsonl rows come from telemetry/golden_dataset.jsonl (auto-collected).
    Both sources are bounded by _GOLDEN_MAX_BYTES.
    """
    items = _read_curated_golden_md()
    items += _read_jsonl_golden_rows()
    return items[:_GOLDEN_MAX]


def _build_rule_set(
    project_root: Path,
    *,
    universal_path: Optional[Path] = None,
    context: tuple[str, ...] = (),
) -> RuleSet:
    """Load and merge Universal + Project + Context rules.

    Universal source: ``~/.claude/devflow/docs/global-rules.md`` (installed by
    install_skills.py). Falls back to repo-local ``docs/global-rules.md`` when
    the installed copy is absent (dev workflow).
    """
    path = universal_path or _UNIVERSAL_RULES_PATH
    if not path.is_file():
        repo_local = Path(__file__).parent.parent / "docs" / "global-rules.md"
        if repo_local.is_file():
            path = repo_local
    return RuleEngine(universal_path=path, project_root=project_root).load(
        context=context
    )
