"""pre_edit_overwrite_guard.py — PreToolUse Write|Edit|MultiEdit hook.

Hard block on any Edit/Write/MultiEdit targeting a file that has been
modified upstream since the last common ancestor with HEAD. Prevents the
classic "Claude edits stale file → push merges blindly → teammate's work
silently overwritten" failure mode.

Behaviour:
  - Skip if file is not inside a git repo
  - Skip if branch has no upstream tracking ref
  - Refresh fetch every 300s (cache: ~/.claude/devflow-lite/state/freshness_cache.json)
  - If `git log HEAD..@{u} -- <file>` returns commits → BLOCK exit 2
  - Block message lists upstream commit authors and the safe fix

Exit 0 always for non-Edit/Write tools, non-git paths, non-existent files.
Exit 2 only when overwrite risk is concrete.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin

CACHE = Path.home() / ".claude/devflow-lite/state/freshness_cache.json"
TTL = 300
FETCH_TIMEOUT = 8
GIT_TIMEOUT = 4


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            cwd=cwd,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _atomic_update_cache(repo: str, ts: float) -> None:
    """Read-modify-write freshness cache atomically.

    Multiple Claude sessions can hit this simultaneously. tempfile + rename
    on the same filesystem is atomic on POSIX, so readers never observe a
    partial write. The whole RMW is not locked, so a concurrent updater can
    still clobber a sibling's entry — but the worst case is one session's
    "I just fetched" timestamp is dropped, triggering one extra fetch on
    that session's next call. Cache is a perf optimisation only.
    """
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, float] = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}
    cache[repo] = ts
    try:
        tmp = CACHE.with_suffix(CACHE.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, CACHE)
    except OSError:
        pass


def _maybe_fetch(repo: str) -> None:
    now = time.time()
    cache: dict[str, float] = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}
    last = float(cache.get(repo, 0))
    if now - last <= TTL:
        return
    try:
        subprocess.run(
            ["git", "fetch", "--quiet"],
            cwd=repo,
            timeout=FETCH_TIMEOUT,
            check=False,
            capture_output=True,
        )
    except Exception:
        pass
    _atomic_update_cache(repo, now)


def _block(file_path: str, upstream: str, authors: list[str], commits: str) -> None:
    foreign = ", ".join(authors) if authors else "remote"
    print(
        f"[devflow:overwrite-guard] BLOCK: '{file_path}' modified on {upstream} "
        f"by {foreign}",
        file=sys.stderr,
    )
    if commits:
        for line in commits.splitlines()[:3]:
            print(f"  upstream: {line}", file=sys.stderr)
    print(
        "  fix: `git pull --rebase` (or merge upstream) before editing — "
        "editing now would silently overwrite remote work on push",
        file=sys.stderr,
    )
    sys.exit(2)


def _extract_paths(tool_name: str, tool_input: dict) -> list[str]:
    fp = tool_input.get("file_path")
    if not fp:
        return []
    return [fp]


def main() -> int:
    payload = read_hook_stdin()
    if not payload:
        return 0
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return 0

    paths = _extract_paths(tool_name, tool_input)
    if not paths:
        return 0
    file_path = paths[0]

    cwd = payload.get("cwd") or os.getcwd()
    repo = _git("rev-parse", "--show-toplevel", cwd=cwd)
    if not repo:
        return 0

    try:
        rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(repo))
    except ValueError:
        return 0
    if rel.startswith("..") or os.path.isabs(rel):
        return 0

    _maybe_fetch(repo)

    upstream = _git("rev-parse", "--abbrev-ref", "@{u}", cwd=repo)
    if not upstream:
        return 0

    commits = _git("log", f"HEAD..{upstream}", "--oneline", "--", rel, cwd=repo)
    if not commits:
        return 0

    authors_raw = _git("log", f"HEAD..{upstream}", "--format=%ae", "--", rel, cwd=repo)
    me = _git("config", "user.email", cwd=repo)
    authors = sorted({a for a in authors_raw.splitlines() if a and a != me})

    _block(rel, upstream, authors, commits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
