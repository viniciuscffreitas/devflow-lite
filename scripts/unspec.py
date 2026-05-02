"""unspec.py — abort the active spec for the current session.

Removes state/<session>/active-spec.json so spec_stop_guard stops blocking
session exit. Idempotent: no-op when there is no active marker.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude/devflow-lite/state"


def _session_id() -> str:
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("DEVFLOW_SESSION_ID")
        or "default"
    )


def main() -> int:
    sid = _session_id()
    marker = STATE_DIR / sid / "active-spec.json"
    if not marker.exists():
        print("[devflow:unspec] no active spec for this session")
        return 0
    try:
        plan = json.loads(marker.read_text()).get("plan_path", "?")
    except Exception:
        plan = "?"
    try:
        marker.unlink()
        print(f"[devflow:unspec] removed: {plan!r}")
    except OSError as e:
        print(f"[devflow:unspec] failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
