"""devflow_status.py — diagnostic CLI for devflow-lite session state.

Subcommands:
  status       — active spec, freshness, locks, recent TDD violations (default)
  locks        — list active edit locks (any session, any worktree)
  unlock PATH  — force-remove the edit lock for PATH (use after stuck session)

Read-only by default; only `unlock` mutates state. Designed to be invoked from
the slash-command `/devflow` — output is plain text, terminal-friendly.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".claude/devflow-lite/state"
LOCKS_DIR = STATE_DIR / "edit_locks"


def _session_id() -> str:
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("DEVFLOW_SESSION_ID")
        or "default"
    )


def _lock_key_for(path: str) -> str:
    canonical = os.path.realpath(path)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _ago(ts: float) -> str:
    delta = int(time.time() - ts)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    return f"{delta // 3600}h ago"


def _print_active_spec(sid: str) -> None:
    marker = STATE_DIR / sid / "active-spec.json"
    print("=== Active spec ===")
    if not marker.exists():
        print("  (none)")
        return
    try:
        data = json.loads(marker.read_text())
    except Exception as e:
        print(f"  (corrupt: {e})")
        return
    print(f"  status:     {data.get('status', '?')}")
    print(f"  plan:       {data.get('plan_path', '?')}")
    print(f"  cwd:        {data.get('cwd', '?')}")
    started = float(data.get("started_at", 0))
    if started:
        print(f"  started:    {_ago(started)}")


def _print_freshness() -> None:
    cache = STATE_DIR / "freshness_cache.json"
    print("=== Freshness ===")
    if not cache.exists():
        print("  (no fetch recorded)")
        return
    try:
        data = json.loads(cache.read_text())
    except Exception:
        print("  (corrupt cache)")
        return
    if not data:
        print("  (empty)")
        return
    for repo, ts in sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        print(f"  {repo}: {_ago(float(ts))}")


def _print_locks() -> int:
    print("=== Edit locks ===")
    if not LOCKS_DIR.exists():
        print("  (none)")
        return 0
    locks = list(LOCKS_DIR.glob("*.json"))
    if not locks:
        print("  (none)")
        return 0
    sid = _session_id()
    for lock in locks:
        try:
            data = json.loads(lock.read_text())
        except Exception:
            continue
        owner = data.get("session_id", "?")
        own = " (this session)" if owner == sid else ""
        print(
            f"  {data.get('path', '?')}\n"
            f"    holder={owner[:8]}{own} pid={data.get('pid', '?')} {_ago(float(data.get('ts', 0)))}"
        )
    return 0


def _print_tdd_violations(sid: str) -> None:
    log = STATE_DIR / sid / "tdd_violations.jsonl"
    print("=== Recent TDD violations ===")
    if not log.exists():
        print("  (none)")
        return
    try:
        lines = log.read_text().splitlines()
    except OSError:
        return
    if not lines:
        print("  (none)")
        return
    for line in lines[-5:]:
        try:
            entry = json.loads(line)
            print(f"  {entry.get('ts', '?')}  {entry.get('file', '?')}")
        except Exception:
            continue


def _unlock(target: str) -> int:
    abs_target = os.path.realpath(target)
    key = _lock_key_for(abs_target)
    lock = LOCKS_DIR / f"{key}.json"
    if not lock.exists():
        print(f"[devflow:unlock] no lock for {abs_target}")
        return 0
    try:
        lock.unlink()
        print(f"[devflow:unlock] removed lock for {abs_target}")
    except OSError as e:
        print(f"[devflow:unlock] failed: {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    args = sys.argv[1:] or ["status"]
    cmd = args[0]
    if cmd == "status":
        sid = _session_id()
        print(f"session: {sid[:8]}")
        _print_active_spec(sid)
        _print_freshness()
        _print_locks()
        _print_tdd_violations(sid)
        return 0
    if cmd == "locks":
        return _print_locks()
    if cmd == "unlock":
        if len(args) < 2:
            print("usage: devflow_status.py unlock <file>", file=sys.stderr)
            return 2
        return _unlock(args[1])
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
