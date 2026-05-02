"""repo_conventions.py — SessionStart hook.

Reads project-local git/PR conventions and emits a
[devflow:repo-conventions] block into Claude's context so the agent
respects team practices instead of imposing personal defaults.

Detects:
  - workflow flavor: trunk-based / gitflow / github-flow
  - rebase vs merge policy (git config pull.rebase + .gitattributes)
  - signed commits required (commit.gpgsign)
  - PR template path (.github/PULL_REQUEST_TEMPLATE*)
  - CONTRIBUTING.md presence
  - default branch name
  - CODEOWNERS presence
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=3, cwd=str(cwd), check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _detect_flavor(cwd: Path) -> str:
    branches = _git("branch", "-a", "--format=%(refname:short)", cwd=cwd)
    has_develop = any(b.endswith("/develop") or b == "develop" for b in branches.splitlines())
    has_release = any("release/" in b for b in branches.splitlines())
    if has_develop and has_release:
        return "gitflow"
    has_main = any(b.endswith("/main") or b == "main" for b in branches.splitlines())
    if has_main and not has_develop:
        prs = (cwd / ".github" / "PULL_REQUEST_TEMPLATE.md").exists() or (cwd / ".github" / "pull_request_template.md").exists()
        return "github-flow" if prs else "trunk-based"
    return "unknown"


def _pr_template_path(cwd: Path) -> str | None:
    for name in (
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/pull_request_template.md",
        ".github/PULL_REQUEST_TEMPLATE",
        "docs/pull_request_template.md",
    ):
        p = cwd / name
        if p.exists():
            return str(p.relative_to(cwd))
    return None


def main() -> int:
    cwd = Path.cwd()
    inside = _git("rev-parse", "--is-inside-work-tree", cwd=cwd)
    if inside != "true":
        return 0

    flavor = _detect_flavor(cwd)
    pull_rebase = _git("config", "--get", "pull.rebase", cwd=cwd) or "false"
    signed = _git("config", "--get", "commit.gpgsign", cwd=cwd) or "false"
    default_branch = (
        _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd).split("/")[-1]
        or "main"
    )
    pr_template = _pr_template_path(cwd)
    contributing = (cwd / "CONTRIBUTING.md").exists()
    codeowners = any(
        (cwd / p / "CODEOWNERS").exists() for p in ("", ".github", "docs")
    )

    fields = [
        f"workflow={flavor}",
        f"default_branch={default_branch}",
        f"pull_rebase={pull_rebase}",
        f"signed_commits={signed}",
        f"pr_template={pr_template or 'none'}",
        f"contributing_md={'yes' if contributing else 'no'}",
        f"codeowners={'yes' if codeowners else 'no'}",
    ]
    print("[devflow:repo-conventions] " + " | ".join(fields))
    return 0


if __name__ == "__main__":
    sys.exit(main())
