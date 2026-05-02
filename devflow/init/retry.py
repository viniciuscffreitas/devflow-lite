"""Init-level retry for shadow composition errors (not test failures)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from knowledge._types import Node

from devflow.init.runner import ShadowResult, run_shadow
from devflow.init.subagent import CompositionFixProposer


class RetryController:
    def __init__(
        self,
        *,
        cap: int = 3,
        token_budget: int = 150_000,
    ) -> None:
        self._cap = cap
        self._budget = token_budget

    def run(
        self,
        root: Path,
        *,
        proposer: CompositionFixProposer,
        session_id: str,
        kb_hits: list[Node] | None = None,
    ) -> tuple[ShadowResult, list[dict]]:
        """Run shadow with retry. Returns (final_result, per_attempt_records).

        Each attempt record captures rc, log_tail, and applied diff so the
        post-mortem writer can show what actually happened — the final
        ShadowResult alone hides attempt count and intermediate failures.
        """
        kb_hits = kb_hits or []
        attempts: list[dict] = []
        state_dir = self._state_dir(session_id)
        if self._budget_blown(state_dir):
            (state_dir / "emergency-halt.log").write_text(
                f"[{int(time.time())}] token budget {self._budget} exceeded — halting init retry\n",
                encoding="utf-8",
            )
            return ShadowResult(rc=70, log_path=state_dir / "halt.log", duration_s=0.0), attempts

        last = run_shadow(root, session_id=session_id)
        attempts.append(self._record(attempt=0, result=last, diff=""))
        if last.rc == 0 or last.rc == 1:
            return last, attempts

        for attempt in range(1, self._cap + 1):
            proposal = proposer.propose(
                root=root,
                shadow_log=self._tail(last.log_path),
                kb_hits=kb_hits,
                attempt=attempt,
                max_attempts=self._cap,
            )
            if proposal is None:
                attempts.append({"attempt": attempt, "rc": last.rc, "log_tail": self._tail(last.log_path), "diff_applied": ""})
                continue

            if not _apply_patch(root, proposal.unified_diff):
                attempts.append({"attempt": attempt, "rc": last.rc, "log_tail": self._tail(last.log_path), "diff_applied": ""})
                continue

            last = run_shadow(root, session_id=session_id)
            attempts.append(self._record(attempt=attempt, result=last, diff=proposal.unified_diff))
            if last.rc == 0:
                return last, attempts

        return last, attempts

    def _record(self, *, attempt: int, result: ShadowResult, diff: str) -> dict:
        return {
            "attempt": attempt,
            "rc": result.rc,
            "log_tail": self._tail(result.log_path),
            "diff_applied": diff,
        }

    def _state_dir(self, session_id: str) -> Path:
        base = os.environ.get("DEVFLOW_STATE_DIR")
        root = Path(base) if base else Path.home() / ".claude" / "devflow" / "state"
        state = root / session_id
        state.mkdir(parents=True, exist_ok=True)
        return state

    def _budget_blown(self, state_dir: Path) -> bool:
        baseline = state_dir / "tokens-baseline.json"
        if not baseline.exists():
            return False
        try:
            data = json.loads(baseline.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Fail open: a corrupt baseline shouldn't halt init. The tripwire exists to
            # prevent runaway token spend; if we can't read it, treat it as absent.
            return False
        delta = int(data.get("total", 0)) - int(data.get("last_pass", 0))
        return delta > self._budget

    @staticmethod
    def _tail(log_path: Path, lines: int = 200) -> str:
        if not log_path.exists():
            return ""
        raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(raw[-lines:])


def _apply_patch(root: Path, unified_diff: str) -> bool:
    if not unified_diff.strip():
        return False
    base_cmd = ["patch", "-p0"]
    try:
        dry = subprocess.run(
            [*base_cmd, "--dry-run"], input=unified_diff,
            capture_output=True, text=True, cwd=root, timeout=30, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    if dry.returncode != 0:
        return False
    try:
        real = subprocess.run(
            base_cmd, input=unified_diff,
            capture_output=True, text=True, cwd=root, timeout=30, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return real.returncode == 0
