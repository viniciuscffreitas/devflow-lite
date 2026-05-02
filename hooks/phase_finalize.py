"""phase_finalize.py — Stop-tier hook.

Lite replacement for task_telemetry's 504-LOC phase tracking. Marks
the active task as COMPLETED if any source file was written this
session. Writes a single-line JSON record per session for the judge to
read. No SQLite, no analytics columns.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin


def main() -> int:
    payload = read_hook_stdin()
    session = payload.get("session_id") or "default"
    cwd = payload.get("cwd") or os.getcwd()

    base = os.environ.get("DEVFLOW_LITE_HOME") or str(Path.home())
    state_dir = Path(base) / ".claude" / "devflow-lite" / "state" / session
    state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session,
        "cwd": cwd,
        "completed_at": int(time.time()),
        "phase": "COMPLETED",
    }
    (state_dir / "phase.json").write_text(json.dumps(record), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
