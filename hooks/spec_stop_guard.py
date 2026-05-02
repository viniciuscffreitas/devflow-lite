"""spec_stop_guard.py — Stop-tier hook (runs inside stop_dispatcher).

Blocks session exit if active-spec.json reports status PENDING /
IMPLEMENTING / in_progress AND the marker belongs to *this* worktree
(cwd match) AND it is not stale (older than 24h).

When a session ends naturally with COMPLETED, the marker is deleted so
the next session of the same id starts clean.

Failure modes are fail-OPEN: corrupt marker → log + allow exit;
unexpected exception → allow exit. Never block forever.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import hook_block, read_hook_stdin

STATE_DIR = Path.home() / ".claude/devflow-lite/state"
SPEC_EXPIRY_SECONDS = 24 * 60 * 60


def _marker_path(session_id: str) -> Path:
    return STATE_DIR / session_id / "active-spec.json"


def _check(marker: Path, cwd: str) -> tuple[bool, str]:
    if not marker.exists():
        return False, ""
    try:
        data = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError) as e:
        try:
            age = time.time() - marker.stat().st_mtime
            if age > SPEC_EXPIRY_SECONDS:
                marker.unlink(missing_ok=True)
                return False, ""
        except OSError:
            pass
        print(
            f"[devflow:spec-guard] corrupt marker, allowing exit: {e}",
            file=sys.stderr,
        )
        return False, ""

    status = data.get("status", "")
    if status == "COMPLETED":
        marker.unlink(missing_ok=True)
        return False, ""
    if status not in ("IMPLEMENTING", "PENDING", "in_progress"):
        return False, ""

    spec_cwd = data.get("cwd")
    if spec_cwd and spec_cwd != cwd:
        return False, ""

    started_at = data.get("started_at", 0)
    if started_at and (time.time() - float(started_at)) > SPEC_EXPIRY_SECONDS:
        return False, ""

    plan = data.get("plan_path", "unknown")
    return True, f"{plan} ({status})"


def main() -> int:
    try:
        payload = read_hook_stdin()
        sid = (
            payload.get("session_id")
            or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("DEVFLOW_SESSION_ID")
        )
        if not sid or sid == "default":
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        active, description = _check(_marker_path(sid), cwd)
        if active:
            reason = (
                f"[devflow] Active spec detected: {description}\n"
                f"Complete it (write status=COMPLETED) or remove "
                f"state/{sid}/active-spec.json to allow exit."
            )
            print(hook_block(reason))
    except Exception as e:
        print(
            f"[devflow:spec-guard] non-fatal: {type(e).__name__}: {e}", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
