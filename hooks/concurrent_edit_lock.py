"""concurrent_edit_lock.py — Pre+Post Tool hook for Write|Edit|MultiEdit.

Prevents two Claude sessions from editing the SAME file at the same time.
Pre acquires a lock keyed by realpath; Post releases it. A claim that has
not been released within TTL seconds is treated as stale and ignored.

Why a hook and not OS file locks: Claude Edit/Write are atomic at the OS
layer (the tool itself rewrites the file in one go) but the *workflow*
window — Read, modify-in-context, Write — is what races. Two sessions
deciding to edit the same file independently produce a last-writer-wins
outcome. The lock blocks the second session before it begins.

Lock file layout: state/edit_locks/<sha256(realpath)[:16]>.json
  { "session_id": "<uuid>", "pid": <int>, "ts": <unix>, "path": "<abs>" }

Self-edits inside the same session reuse their own lock without blocking,
so MultiEdit / sequential Edits on the same file are not blocked.

Exit codes:
  0 — acquired or released cleanly, or non-edit tool (no-op)
  2 — peer session holds an active lock — BLOCK with diagnostic
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin

LOCKS_DIR = Path.home() / ".claude/devflow-lite/state/edit_locks"
TTL_SECONDS = 90
EDIT_TOOLS = {"Write", "Edit", "MultiEdit"}


def _key_for(path: str) -> str:
    canonical = os.path.realpath(path)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _lock_path(path: str) -> Path:
    return LOCKS_DIR / f"{_key_for(path)}.json"


def _session_id() -> str:
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if not sid:
        sid = os.environ.get("DEVFLOW_SESSION_ID", "").strip()
    return sid or "default"


def _read_lock(lock: Path) -> dict | None:
    if not lock.exists():
        return None
    try:
        return json.loads(lock.read_text())
    except Exception:
        return None


def _atomic_write(lock: Path, data: dict) -> None:
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = lock.with_suffix(lock.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(data))
        os.replace(tmp, lock)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _block(file_path: str, holder: dict) -> None:
    other_sid = holder.get("session_id", "?")
    other_pid = holder.get("pid", "?")
    age = int(time.time() - float(holder.get("ts", 0)))
    print(
        f"[devflow:edit-lock] BLOCK: '{file_path}' is being edited by another "
        f"Claude session (id={other_sid[:8]} pid={other_pid} {age}s ago)",
        file=sys.stderr,
    )
    print(
        "  fix: wait for that session to finish, or close it. "
        f"Stale locks auto-expire after {TTL_SECONDS}s.",
        file=sys.stderr,
    )
    sys.exit(2)


def _acquire(file_path: str, sid: str) -> int:
    lock = _lock_path(file_path)
    holder = _read_lock(lock)
    now = time.time()
    if holder:
        ts = float(holder.get("ts", 0))
        holder_sid = str(holder.get("session_id", ""))
        is_self = holder_sid == sid
        is_fresh = (now - ts) < TTL_SECONDS
        if not is_self and is_fresh:
            _block(file_path, holder)
    _atomic_write(
        lock,
        {
            "session_id": sid,
            "pid": os.getpid(),
            "ts": now,
            "path": os.path.realpath(file_path),
        },
    )
    return 0


def _release(file_path: str, sid: str) -> int:
    lock = _lock_path(file_path)
    holder = _read_lock(lock)
    if not holder:
        return 0
    if str(holder.get("session_id", "")) == sid:
        try:
            lock.unlink()
        except OSError:
            pass
    return 0


def main() -> int:
    payload = read_hook_stdin()
    if not payload:
        return 0
    tool_name = payload.get("tool_name", "")
    if tool_name not in EDIT_TOOLS:
        return 0
    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    event = payload.get("hook_event_name", "")
    sid = _session_id()
    if event == "PostToolUse":
        return _release(file_path, sid)
    return _acquire(file_path, sid)


if __name__ == "__main__":
    sys.exit(main())
