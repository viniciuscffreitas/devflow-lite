"""PostToolUse hook (broad matcher) — monitors context window usage.
Warns at ~80% and ~90% with contextual hints:
  - If an IMPLEMENTING spec is active: suggest /compact focus on <plan_path>
  - Otherwise: suggest /compact focus on current task, or /clear
  - At 90%: additionally mention rewind (Esc Esc) for recent wrong turns
Non-blocking; every error path exits 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    AUTOCOMPACT_BUFFER_TOKENS,
    CONTEXT_CAUTION_PCT,
    CONTEXT_WARN_PCT,
    CONTEXT_WINDOW_TOKENS,
    get_session_id,
    get_state_dir,
    hook_context,
    read_hook_stdin,
)

TOKEN_DELTA_GUARD = 150_000
_BASELINE_FILE = "tokens-baseline.json"
_EMERGENCY_HALT_FILE = "emergency-halt.log"

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


def _get_window(hook_data: dict) -> int:
    """Return the context window size from hook payload, falling back to constant.

    Reads context_window_tokens from the hook data so Opus 4.6 / Sonnet 4.6
    (1M token context) don't trigger premature warnings from a hardcoded value.
    """
    payload_window = hook_data.get("context_window_tokens", 0)
    if payload_window and payload_window > 0:
        return int(payload_window)
    return CONTEXT_WINDOW_TOKENS


def tokens_to_pct(tokens_used: int, window: int = CONTEXT_WINDOW_TOKENS) -> float:
    compaction_threshold = window - AUTOCOMPACT_BUFFER_TOKENS
    if compaction_threshold <= 0:
        return 100.0
    return min(100.0, (tokens_used / compaction_threshold) * 100)


def _active_spec_plan() -> Optional[str]:
    """Return plan_path if an IMPLEMENTING spec is active, else None.

    Fails silently on missing/corrupt state — the hook must never crash.
    """
    try:
        spec_file = get_state_dir() / "active-spec.json"
        if not spec_file.exists():
            return None
        data = json.loads(spec_file.read_text())
        if data.get("status") != "IMPLEMENTING":
            return None
        plan = data.get("plan_path")
        return plan if isinstance(plan, str) and plan.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def _last_verdict(session_id: str) -> Optional[str]:
    """Return most-recent judge_verdict for the session (or None)."""
    if TelemetryStore is None or not session_id:
        return None
    try:
        from contextlib import closing
        with closing(TelemetryStore()._connect()) as conn:
            conn.execute("PRAGMA busy_timeout = 3000")
            row = conn.execute(
                "SELECT judge_verdict FROM task_executions "
                "WHERE session_id = ? AND judge_verdict IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return row["judge_verdict"] if row is not None else None
    except Exception:
        return None


def _baseline_path(state_dir: Path) -> Path:
    return state_dir / _BASELINE_FILE


def _read_baseline(state_dir: Path) -> Optional[int]:
    path = _baseline_path(state_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return int(data.get("baseline")) if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _write_baseline(state_dir: Path, tokens: int) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        _baseline_path(state_dir).write_text(json.dumps({"baseline": int(tokens)}))
    except OSError:
        pass


def _check_token_delta_guard(tokens_used: int, state_dir: Path) -> Optional[str]:
    """Track baseline tokens per loop; fire Emergency Halt if delta > TOKEN_DELTA_GUARD.

    Baseline resets when the last judge verdict for this session is 'pass'
    (the retry loop succeeded — start fresh). Otherwise the baseline persists
    across ticks so we can measure burn for the ongoing failure loop.

    Returns the emergency-halt message when the guard fires, else None.
    """
    session_id = get_session_id()
    verdict = _last_verdict(session_id)

    # Guard is only armed while an active retry loop is burning tokens
    # (last verdict == 'fail'). Outside a failure loop reset the baseline
    # so a normal long-running session doesn't trip the halt.
    if verdict != "fail":
        _write_baseline(state_dir, tokens_used)
        return None

    baseline = _read_baseline(state_dir)
    if baseline is None:
        _write_baseline(state_dir, tokens_used)
        return None

    delta = tokens_used - baseline
    if delta <= TOKEN_DELTA_GUARD:
        return None

    halt_path = state_dir / _EMERGENCY_HALT_FILE
    if halt_path.exists():
        return None  # already halted, don't re-emit

    msg = (
        f"[devflow:EMERGENCY_HALT] Token Delta Guard disparou. "
        f"Delta={delta} tokens sem verdict='pass' (limite={TOKEN_DELTA_GUARD}). "
        f"Sessão encerrada. Aguarde clarificação humana."
    )
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        halt_path.write_text(
            f"session={session_id}\n"
            f"tokens_used={tokens_used}\n"
            f"baseline={baseline}\n"
            f"delta={delta}\n"
            f"last_verdict={verdict or 'none'}\n"
        )
    except OSError:
        pass
    return msg


def _build_hint(pct: float, spec_plan: Optional[str]) -> str:
    """Compose the 80%/90% message with a contextual suggestion."""
    if spec_plan:
        action = f"/compact focus on {spec_plan}, drop unrelated exploration"
    else:
        action = "/compact focus on current task, or /clear if switching tasks"

    if pct >= CONTEXT_CAUTION_PCT:
        return (
            f"[devflow] Context at {pct:.0f}% — autocompact imminent. "
            f"{action}. For recent wrong turns, use Esc Esc (rewind)."
        )
    return f"[devflow] Context at {pct:.0f}% — {action}."


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        tokens_used = hook_data.get("context_tokens_used", 0)
        if not tokens_used:
            return 0

        window = _get_window(hook_data)
        pct = tokens_to_pct(tokens_used, window=window)

        state_dir = get_state_dir()
        halt_msg = _check_token_delta_guard(tokens_used, state_dir)
        if halt_msg is not None:
            print(hook_context(halt_msg))
            return 0

        if pct < CONTEXT_WARN_PCT:
            return 0

        spec_plan = _active_spec_plan()
        msg = _build_hint(pct, spec_plan)
        print(hook_context(msg))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
