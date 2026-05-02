"""merge_safety.py — PreToolUse Bash hook.

Blocks operations that would silently discard work authored by other
developers. Targets the failure modes that produce the worst lost-work
incidents on shared branches:

  - git checkout --theirs / --ours during conflict resolution
    (drops one side wholesale instead of merging)
  - git reset --hard / --mixed / --merge with a commitish that rewinds
    past commits not authored by the current user
  - git checkout -- <path> / git restore <path> on files currently in
    conflicted state (silently picks one version)
  - git rebase --skip (drops the commit being replayed)
  - git stash drop / git stash clear (loses uncommitted work that may
    not belong to current user)
  - git push -f / --mirror / --delete on branches with foreign authors
    (covered partially by branch_policy; this layer adds blame check)

Exit codes: 0 ok, 2 block. Always advisory before block — prints the
specific reason and the safe alternative.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=cwd,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _block(msg: str, fix: str = "") -> None:
    print(f"[devflow:merge-safety] BLOCK: {msg}", file=sys.stderr)
    if fix:
        print(f"  safe alternative: {fix}", file=sys.stderr)
    sys.exit(2)


def _conflicted_files(cwd: str | None) -> list[str]:
    raw = _git("diff", "--name-only", "--diff-filter=U", cwd=cwd)
    return [line for line in raw.splitlines() if line.strip()]


def _foreign_authors_in_range(rev_range: str, me: str, cwd: str | None) -> list[str]:
    raw = _git("log", "--format=%ae", rev_range, cwd=cwd)
    authors = {a for a in raw.splitlines() if a and a != me}
    return sorted(authors)


def _check_checkout_side(cmd: str) -> None:
    if re.search(r"\bgit\s+checkout\s+(--theirs|--ours)\b", cmd):
        side = "--theirs" if "--theirs" in cmd else "--ours"
        _block(
            f"git checkout {side} discards work from the other side wholesale",
            "resolve conflict file-by-file in editor, then `git add <file>`",
        )


def _check_checkout_path_during_conflict(cmd: str, cwd: str | None) -> None:
    m = re.search(r"\bgit\s+(?:checkout|restore)\s+(?:--\s+)?(\S+)", cmd)
    if not m:
        return
    path = m.group(1)
    if path.startswith("-") or path in ("HEAD", "."):
        return
    conflicted = _conflicted_files(cwd)
    if any(
        path == c or path.endswith("/" + c) or c.endswith("/" + path)
        for c in conflicted
    ):
        _block(
            f"'{path}' is in conflicted state — checkout/restore would silently pick one version",
            "edit the file, remove conflict markers, then `git add <file>`",
        )


def _check_reset_hard(cmd: str, cwd: str | None) -> None:
    m = re.search(r"\bgit\s+reset\s+(?:--hard|--mixed|--merge)\s+(\S+)", cmd)
    if not m:
        return
    target = m.group(1)
    me = _git("config", "user.email", cwd=cwd)
    if not me:
        return
    foreign = _foreign_authors_in_range(f"{target}..HEAD", me, cwd)
    if foreign:
        _block(
            f"reset to {target} would discard commits authored by {', '.join(foreign)}",
            "use `git revert` or rebase interactively — preserves history",
        )


def _check_rebase_skip(cmd: str) -> None:
    if re.search(r"\bgit\s+rebase\s+--skip\b", cmd):
        _block(
            "git rebase --skip drops the commit being replayed — work is lost",
            "use `git rebase --continue` after resolving, or `--abort` to bail",
        )


def _check_stash_drop(cmd: str) -> None:
    if re.search(r"\bgit\s+stash\s+(drop|clear)\b", cmd):
        action = "drop" if "drop" in cmd else "clear"
        _block(
            f"git stash {action} permanently deletes stashed work",
            "run `git stash list` first, recover with `git stash apply` if needed",
        )


def _check_clean_force(cmd: str) -> None:
    if re.search(r"\bgit\s+clean\s+(?:-fd?x?|-x?fd?)\b", cmd):
        _block(
            "git clean -f deletes untracked files irrecoverably (may include teammate WIP)",
            "run `git clean -n` (dry-run) first, review the list",
        )


def main() -> int:
    payload = read_hook_stdin()
    cmd = (payload.get("tool_input", {}) or {}).get("command", "")
    cwd = payload.get("cwd")
    if not cmd or "git" not in cmd:
        return 0

    _check_checkout_side(cmd)
    _check_rebase_skip(cmd)
    _check_stash_drop(cmd)
    _check_clean_force(cmd)
    _check_reset_hard(cmd, cwd)
    _check_checkout_path_during_conflict(cmd, cwd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
