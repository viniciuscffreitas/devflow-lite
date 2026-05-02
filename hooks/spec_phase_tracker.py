"""spec_phase_tracker.py — UserPromptSubmit hook.

Detects `/spec <description>` in the user prompt and writes a PENDING
marker at state/<session>/active-spec.json. Deterministic — no LLM
required for the PENDING transition. The skill itself is responsible
for IMPLEMENTING and COMPLETED.

Output marker schema (the same shape spec_stop_guard reads):
  {"status": "PENDING", "plan_path": "<desc>",
   "started_at": <unix>, "cwd": "<abs path>"}

cwd is recorded so multi-worktree parallel sessions do not cross-block
each other when one hits Stop.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin

STATE_DIR = Path.home() / ".claude/devflow-lite/state"
_SPEC_RE = re.compile(r"/spec\s*(.*)", re.IGNORECASE)


def _extract_description(prompt: str) -> str:
    m = _SPEC_RE.search(prompt.strip())
    if not m:
        return "unnamed spec"
    desc = m.group(1).strip().strip('"').strip("'")
    return desc or "unnamed spec"


def _write_pending(session_id: str, description: str, cwd: str) -> None:
    sdir = STATE_DIR / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    marker = {
        "status": "PENDING",
        "plan_path": description,
        "started_at": int(time.time()),
        "cwd": cwd,
    }
    target = sdir / "active-spec.json"
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(marker), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def main() -> int:
    try:
        payload = read_hook_stdin()
        prompt = payload.get("prompt", "") or ""
        if "/spec" not in prompt:
            return 0
        sid = (
            payload.get("session_id")
            or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("DEVFLOW_SESSION_ID")
            or "default"
        )
        cwd = payload.get("cwd") or os.getcwd()
        desc = _extract_description(prompt)
        _write_pending(sid, desc, cwd)
        print(f"[devflow:spec] PENDING — {desc!r}", file=sys.stderr)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
