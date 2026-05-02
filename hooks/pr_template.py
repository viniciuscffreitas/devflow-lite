"""pr_template.py — Stop-tier hook.

Generates a PR body draft based on the current branch's commits and
diff. Respects .github/PULL_REQUEST_TEMPLATE.md when present (uses it
as the skeleton and fills sections from commit data).

Output: writes draft to state/<session>/pr-draft.md and prints the
path to stdout. Never blocks.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin


CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
    r"(\([^)]+\))?(!)?:\s+(.+)$"
)


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _default_branch(cwd: Path) -> str:
    head = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd)
    return head.split("/")[-1] if head else "main"


def _commits_ahead(cwd: Path, base: str) -> list[tuple[str, str]]:
    raw = _git("log", f"{base}..HEAD", "--format=%h%x09%s", cwd=cwd)
    if not raw:
        return []
    return [tuple(line.split("\t", 1)) for line in raw.splitlines() if "\t" in line]  # type: ignore[misc]


def _classify(commits: list[tuple[str, str]]) -> str:
    types: set[str] = set()
    for _, subj in commits:
        m = CONVENTIONAL.match(subj)
        if m:
            types.add(m.group(1))
    if "fix" in types and "feat" not in types:
        return "fix"
    if "feat" in types:
        return "feat"
    if types:
        return next(iter(types))
    return "chore"


def _read_pr_template(repo: Path) -> str | None:
    for rel in (
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/pull_request_template.md",
        "docs/pull_request_template.md",
    ):
        p = repo / rel
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _build_default(kind: str, commits: list[tuple[str, str]], diff_stat: str) -> str:
    lines = ["## What changed", ""]
    for _, subj in commits:
        lines.append(f"- {subj}")
    lines += ["", "## Why", "", "<!-- explain motivation -->", ""]
    lines += ["## How to test", "", "<!-- steps for reviewer -->", ""]
    lines += ["## Risk / rollback", "", "<!-- impact + revert plan -->", ""]
    if kind == "fix":
        lines += [
            "## Behavior contract",
            "",
            "- CHANGES: <!-- behavior that flips after merge -->",
            "- MUST NOT CHANGE: <!-- callers/contracts preserved -->",
            "- PROOF: <!-- test names that lock the contract -->",
            "",
        ]
    if diff_stat:
        lines += ["## Diff stat", "", "```", diff_stat, "```", ""]
    return "\n".join(lines)


def main() -> int:
    payload = read_hook_stdin()
    cwd = Path(payload.get("cwd") or os.getcwd())
    session = payload.get("session_id") or "default"

    if _git("rev-parse", "--is-inside-work-tree", cwd=cwd) != "true":
        return 0

    base = _default_branch(cwd)
    commits = _commits_ahead(cwd, f"origin/{base}") or _commits_ahead(cwd, base)
    if not commits:
        return 0

    kind = _classify(commits)
    diff_stat = _git("diff", "--stat", f"{base}...HEAD", cwd=cwd)

    template = _read_pr_template(cwd)
    body = template if template else _build_default(kind, commits, diff_stat)

    home_base = os.environ.get("DEVFLOW_LITE_HOME") or str(Path.home())
    state_dir = Path(home_base) / ".claude" / "devflow-lite" / "state" / session
    state_dir.mkdir(parents=True, exist_ok=True)
    out = state_dir / "pr-draft.md"
    out.write_text(body, encoding="utf-8")

    print(f"[devflow:pr-draft] {kind} | {len(commits)} commit(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
