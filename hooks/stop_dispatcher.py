"""stop_dispatcher_slim.py — single Stop entry point for devflow-lite.

Runs (in order, sync):
  1. phase_finalize    — writes COMPLETED marker
  2. pr_template       — drafts PR body for current branch
  3. post_task_judge   — LLM verdict on the diff (PASS/WARN/FAIL)

Replaces the 376-LOC dispatcher of devflow-cloud which orchestrated
6 hooks plus shadow audit, instinct capture, cost tracking and
boundary detection — none of which are part of lite.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import time
from pathlib import Path

_HOOKS_DIR = Path(__file__).parent
sys.path.insert(0, str(_HOOKS_DIR))

from _stdin_cache import get as _cache_get  # noqa: E402

_STATE_BASE = Path.home() / ".claude/devflow-lite/state"

_PIPELINE = ["spec_stop_guard", "phase_finalize", "pr_template", "post_task_judge"]


def _log_hook(
    session_id: str, hook: str, rc: int, elapsed_ms: int, error: str | None
) -> None:
    """Append per-hook execution record to state/<sid>/dispatcher.log.

    Plain JSON-lines so /devflow status (or grep) can read it. Failure to log
    is silent: dispatcher must never block Stop because logging broke.
    """
    if not session_id or session_id == "default":
        return
    try:
        sdir = _STATE_BASE / session_id
        sdir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "hook": hook,
            "rc": rc,
            "elapsed_ms": elapsed_ms,
        }
        if error:
            entry["error"] = error
        with (sdir / "dispatcher.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _read_stdin() -> str:
    cached = _cache_get()
    if cached:
        return json.dumps(cached)
    try:
        return sys.stdin.read()
    except OSError:
        return "{}"


def _run(name: str, stdin_data: str, session_id: str) -> int:
    started = time.time()
    err: str | None = None
    rc = 0
    try:
        spec = importlib.util.spec_from_file_location(name, _HOOKS_DIR / f"{name}.py")
        if spec is None or spec.loader is None:
            return 0
        module = importlib.util.module_from_spec(spec)
        sys.stdin = io.StringIO(stdin_data)
        spec.loader.exec_module(module)
        rc = int(module.main()) if hasattr(module, "main") else 0
    except SystemExit as e:
        rc = int(e.code or 0)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[devflow:dispatcher] {name} failed: {err}", file=sys.stderr)
        rc = 0
    finally:
        elapsed_ms = int((time.time() - started) * 1000)
        _log_hook(session_id, name, rc, elapsed_ms, err)
    return rc


def _extract_session_id(stdin_data: str) -> str:
    try:
        payload = json.loads(stdin_data) if stdin_data else {}
    except json.JSONDecodeError:
        payload = {}
    return (
        payload.get("session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("DEVFLOW_SESSION_ID")
        or "default"
    )


def main() -> int:
    stdin_data = _read_stdin()
    session_id = _extract_session_id(stdin_data)
    final_exit = 0
    for hook in _PIPELINE:
        rc = _run(hook, stdin_data, session_id)
        if rc != 0:
            final_exit = rc
    return final_exit


if __name__ == "__main__":
    sys.exit(main())
