"""
Stop hook — LLM-as-judge orchestrator.

Runs after a task completes. Reads oversight_level from risk-profile.json,
evaluates the diff via HarnessJudge, routes result through JudgeRouter,
updates TelemetryStore, and exits with the router's exit code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# Skip evaluation when running inside a Paperweight subprocess.
# Paperweight sets PAPERWEIGHT_RUN_ID for all claude -p calls it dispatches.
# Without this guard, post_task_judge fires after EVERY pipeline phase
# instead of once at the end of the complete task.
import os as _os

if _os.environ.get("PAPERWEIGHT_RUN_ID"):
    sys.exit(0)

try:
    from _judge_inputs import (  # noqa: E402
        _build_rule_set,
        _read_existing_code,
        _read_feature_path,
        _read_golden_examples,
        _read_harness_rules,
        _read_spec,
    )
    from _util import get_session_id, get_state_dir, hook_block, read_oversight_level  # noqa: E402
    from judge.evaluator import HarnessJudge, JudgePayload  # noqa: E402
    from judge.router import JudgeRouter  # noqa: E402
except ImportError:

    def main(*_a, **_kw) -> int:  # noqa: D401 — graceful no-op when judge deps absent
        return 0

    if __name__ == "__main__":
        sys.exit(0)
    sys.exit(0)

MAX_RETRIES = 3
_RETRIES_FILE = "retries.json"
_POST_MORTEM_FILE = "post-mortem.md"
_EMERGENCY_HALT_FILE = "emergency-halt.log"

_CRITICAL_RETRY_TEMPLATE = (
    "[devflow:CRITICAL_RETRY] Falha detectada pelo juiz (tentativa {attempt}/{max_attempts}). "
    "Não pare a execução. Use o reasoning abaixo para aplicar correções imediatas e "
    "reinicie o ciclo de verificação automaticamente.\n"
    "fail_reasons: {reasons}\n"
    "reasoning: {reasoning}"
)

_HALTED_TEMPLATE = (
    "[devflow:HALTED_FOR_REVIEW] Limite de {max_attempts} tentativas atingido para task {task_id}. "
    "Post-mortem salvo em {post_mortem}. Aguarde clarificação humana antes de prosseguir."
)

_EMERGENCY_HALT_RESPECT = (
    "[devflow:EMERGENCY_HALT_RESPECT] {halt_file} presente — Token Delta Guard ativou. "
    "Loop de retry suspenso. Aguarde clarificação humana."
)

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


def _get_state_dir(session_id: Optional[str] = None) -> Path:
    """Resolve the per-session state dir.

    When ``session_id`` is provided, build the path explicitly from
    ``current_paths().state / session_id`` so the emergency-halt and
    retry checks stay session-scoped even when invoked outside a hook
    context (e.g. ``python -m hooks.post_task_judge --session-id ...``).
    Falls back to ``get_state_dir()`` otherwise (env-driven hook path).
    """
    if session_id:
        from _paths import current_paths

        state_dir = current_paths().state / session_id
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir
    return get_state_dir()


def _get_diff(cwd: Path) -> str:
    """Return `git diff HEAD~1` or unstaged diff from `cwd`, or '' on failure."""
    for cmd in [["git", "diff", "HEAD~1"], ["git", "diff"]]:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                return result.stdout
        except Exception:
            pass
    return ""


def _peek_tdd_violations(state_dir: Path) -> list:
    """Read pending TDD violations from active_signals WITHOUT consuming them.

    Used by the empty-diff path so the violation survives until the next turn
    that actually produces a diff — closing signal-loss point #3 from the
    Tier-2 diagnostic.
    """
    session_id = state_dir.name
    try:
        from telemetry.store import get_store

        signals = get_store().peek_signals(session_id, "tdd_violation")
        return [s["payload"].get("file") for s in signals if s["payload"].get("file")]
    except Exception as e:
        from _logger import log_error

        log_error(
            "tdd_violation_peek_failed",
            details={"session_id": session_id, "error": f"{type(e).__name__}: {e}"},
            hook="post_task_judge",
        )
        return []


def _consume_tdd_violations(state_dir: Path) -> list:
    """Read and DELETE TDD violations for this session from active_signals.

    Returns list of reason strings (e.g. "Missing Test Coverage: foo.py").
    Signals are removed from the store so a subsequent task starts clean.
    """
    session_id = state_dir.name
    try:
        from telemetry.store import get_store

        signals = get_store().consume_signals(session_id, "tdd_violation")
        return [
            f"Missing Test Coverage: {s['payload'].get('file')}"
            for s in signals
            if s["payload"].get("file")
        ]
    except Exception:
        return []


def _consume_subagent_reports(state_dir: Path) -> tuple[list, list]:
    """Consume Tier-4 specialist worker reports.

    Returns `(hard_fail_reasons, soft_notes)`:
      * hard_fail_reasons — ONLY Worker-Sec status=unsafe. These flip the
        judge verdict to FAIL (via `JudgePayload.forced_fail_reasons`).
      * soft_notes — Worker-QA and Worker-Doc non-"ok" statuses. These are
        attached to `fail_reasons` for diagnostic context but DO NOT flip
        the verdict on their own (via `JudgePayload.soft_fail_notes`).

    Reports are written by `subagent_tracker.record_report` as
    `subagent_report` active_signals. Signals are DELETED on read so the
    next task starts clean — mirrors `_consume_tdd_violations` and
    `_consume_shadow_errors`.

    Fail-closed sentinel: if the store itself raises, emit a sentinel hard
    reason so a Worker-Sec=unsafe cannot be silently lost to a DB failure.
    """
    session_id = state_dir.name
    try:
        from telemetry.store import get_store

        signals = get_store().consume_signals(session_id, "subagent_report")
    except Exception as e:
        from _logger import log_error

        log_error(
            "subagent_reports_consume_failed",
            details={"session_id": session_id, "error": f"{type(e).__name__}: {e}"},
            hook="post_task_judge",
        )
        return (["[sec] swarm-reports-unavailable: store error — treat as unsafe"], [])

    hard: list[str] = []
    soft: list[str] = []
    for s in signals:
        payload = s.get("payload") or {}
        worker = (payload.get("worker") or "").lower()
        status = (payload.get("status") or "").lower()
        summary = payload.get("summary") or ""
        if worker == "sec" and status == "unsafe":
            hard.append(f"[sec] unsafe: {summary}" if summary else "[sec] unsafe")
        elif worker == "qa" and status not in ("", "ok"):
            soft.append(f"[qa] {status}: {summary}" if summary else f"[qa] {status}")
        elif worker == "doc" and status not in ("", "ok"):
            soft.append(f"[doc] {status}: {summary}" if summary else f"[doc] {status}")
    return (hard, soft)


def _consume_shadow_errors(state_dir: Path) -> list:
    """Read and DELETE shadow-test failures for this session.

    Each consumed signal becomes a forced-fail reason so the judge flips the
    verdict to 'fail', triggering the auto-retry loop.
    """
    session_id = state_dir.name
    try:
        from telemetry.store import get_store

        signals = get_store().consume_signals(session_id, "shadow_error")
        reasons = []
        for s in signals:
            summary = s["payload"].get("summary") or "no summary"
            # "[shadow]" prefix lets downstream code branch on source
            # without parsing the free-text portion.
            reasons.append(f"[shadow] Test Failed: {summary}")
        return reasons
    except Exception:
        return []


from _shadow_audit import _consume_shadow_audits, append_to_wiki_log  # noqa: E402,F401


def _retries_path(state_dir: Path) -> Path:
    return state_dir / _RETRIES_FILE


def _read_retries(state_dir: Path) -> dict:
    path = _retries_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_retries(state_dir: Path, data: dict) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        _retries_path(state_dir).write_text(json.dumps(data))
    except OSError:
        pass


def _bump_retry(state_dir: Path, task_id: str) -> int:
    data = _read_retries(state_dir)
    count = int(data.get(task_id, 0)) + 1
    data[task_id] = count
    _write_retries(state_dir, data)
    return count


def _clear_retry(state_dir: Path, task_id: str) -> None:
    data = _read_retries(state_dir)
    if task_id in data:
        del data[task_id]
        _write_retries(state_dir, data)


def _write_post_mortem(state_dir: Path, task_id: str, result, attempts: int) -> Path:
    """Compose a post-mortem markdown explaining why the loop halted."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / _POST_MORTEM_FILE
    reasons = ", ".join(result.fail_reasons or []) or "(none)"
    reasoning = (result.raw_response or "(no reasoning captured)")[:2000]
    body = (
        f"# Post-mortem — task {task_id}\n\n"
        f"**Attempts:** {attempts} / {MAX_RETRIES}\n"
        f"**Final verdict:** {result.verdict}\n"
        f"**Fail reasons:** {reasons}\n\n"
        f"## Last reasoning\n```\n{reasoning}\n```\n\n"
        f"## Human clarification needed\n"
        f"- Was the contract/spec clear enough for this change?\n"
        f"- Are there hidden constraints the judge keeps flagging?\n"
        f"- Should this task be split or should the rubric be relaxed?\n"
    )
    try:
        path.write_text(body)
    except OSError:
        pass
    return path


def _emergency_halt_active(state_dir: Path) -> Optional[Path]:
    """Return the emergency-halt log path if Token Delta Guard fired, else None."""
    path = state_dir / _EMERGENCY_HALT_FILE
    return path if path.exists() else None


def _is_already_judged(task_id: str, store=None) -> bool:
    """Check if this task already has a judge_verdict in TelemetryStore.

    Accepts an optional store to avoid creating a second TelemetryStore()
    instance when called from run() which already holds one.
    """
    if TelemetryStore is None:
        return False
    try:
        from contextlib import closing

        s = store if store is not None else TelemetryStore()
        with closing(s._connect()) as conn:
            conn.execute("PRAGMA busy_timeout = 3000")
            row = conn.execute(
                "SELECT judge_verdict FROM task_executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row is not None and row["judge_verdict"] is not None
    except Exception:
        return False


def run(
    state_dir: Path,
    project_root: Optional[Path] = None,
    session_id_override: Optional[str] = None,
) -> int:
    state_dir = Path(state_dir)

    # Read oversight_level — default to "strict" when profile absent (fail-safe)
    oversight_level = read_oversight_level(state_dir, default="strict")

    router = JudgeRouter()

    if not router.should_run(oversight_level):
        print("[devflow:judge] skipped (vibe)")
        return 0

    task_id = session_id_override or get_session_id()

    # Build store once — reused for both the duplicate check and the verdict write
    store = None
    if TelemetryStore is not None:
        try:
            store = TelemetryStore()
        except Exception:
            pass

    # Double-judging guard: skip if boundary judge already evaluated this task
    if _is_already_judged(task_id, store=store):
        print("[devflow:judge] skipped (already judged by boundary judge)")
        return 0

    # Build payload
    if project_root is None:
        from _project_root import detect_project_root

        project_root = detect_project_root()
    diff = _get_diff(project_root)

    # Empty-diff precondition: a planning/conversation turn, or a cwd that is
    # not a git repo, yields an empty diff. Feeding that to the LLM makes it
    # emit a phantom FAIL verdict on `user_intent` and pollutes telemetry +
    # the reflection hook. Skip early, but NOTE any pending TDD violation so
    # it survives to the next diff-emitting turn (signal-loss point #3).
    if not diff.strip():
        pending_violations = _peek_tdd_violations(state_dir)
        if pending_violations:
            from _logger import log_error

            log_error(
                "tdd_violation_dropped_empty_diff",
                details={"files": pending_violations, "task_id": task_id},
                hook="post_task_judge",
            )
        print(f"[devflow:judge] skipped {task_id} (no diff to evaluate)")
        if store is not None:
            try:
                store.record(
                    {
                        "task_id": task_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": task_id,
                        "oversight_level": oversight_level,
                        "judge_verdict": "skipped_no_diff",
                    }
                )
            except Exception as e:
                from _logger import log_error

                log_error(
                    "telemetry_record_failed",
                    details={"task_id": task_id, "error": f"{type(e).__name__}: {e}"},
                    hook="post_task_judge",
                )
        return 0

    swarm_hard, swarm_soft = _consume_subagent_reports(state_dir)
    # Drain audit signals alongside fail-reason drains. Return value is an
    # empty list by contract — observability without rubric drift.
    _consume_shadow_audits(state_dir, project_root=project_root)
    rule_set = _build_rule_set(project_root)
    payload = JudgePayload(
        diff=diff,
        spec=_read_spec(state_dir),
        harness_rules=_read_harness_rules(project_root),
        existing_code=_read_existing_code(diff),
        feature_path=_read_feature_path(state_dir),
        task_id=task_id,
        golden_examples=_read_golden_examples(),
        forced_fail_reasons=(
            _consume_tdd_violations(state_dir)
            + _consume_shadow_errors(state_dir)
            + swarm_hard
        ),
        soft_fail_notes=swarm_soft,
        rule_set=rule_set,
    )

    # Evaluate
    judge = HarnessJudge()
    result = judge.evaluate(payload)

    # If judge returned "skipped" (timeout, parse error), record as judge_error
    verdict = result.verdict
    if verdict == "skipped":
        verdict = "judge_error"

    # Route
    exit_code = router.handle(oversight_level, result, state_dir)

    # Circuit Breaker — auto-retry loop with bounded attempts
    if verdict == "pass":
        _clear_retry(state_dir, task_id)
        from _judge_kb import record_task_pass_in_kb

        record_task_pass_in_kb(task_id, state_dir, result, project_root)
    elif verdict == "fail":
        halt_file = _emergency_halt_active(state_dir)
        if halt_file is not None:
            print(hook_block(_EMERGENCY_HALT_RESPECT.format(halt_file=halt_file)))
        else:
            count = _bump_retry(state_dir, task_id)
            if count >= MAX_RETRIES:
                pm_path = _write_post_mortem(state_dir, task_id, result, count)
                print(
                    hook_block(
                        _HALTED_TEMPLATE.format(
                            max_attempts=MAX_RETRIES,
                            task_id=task_id,
                            post_mortem=pm_path,
                        )
                    )
                )
                try:
                    from e2r_post_mortem import (
                        detect_systemic_patterns,
                        draft_rule,
                        write_drafts,
                    )

                    state_root = state_dir.parent
                    patterns = detect_systemic_patterns(state_root, threshold=3)
                    if patterns:
                        drafts = [draft_rule(p) for p in patterns]
                        out_dir = state_dir / "proposed-rules"
                        write_drafts(out_dir, drafts)
                        print(
                            f"[devflow:e2r] {len(drafts)} candidate rule(s) drafted at {out_dir}"
                        )
                except Exception as e:
                    from _logger import log_error

                    log_error(
                        "e2r_draft_failed",
                        details={
                            "task_id": task_id,
                            "error": f"{type(e).__name__}: {e}",
                        },
                        hook="post_task_judge",
                    )
                _clear_retry(state_dir, task_id)
            else:
                reasons = ", ".join(result.fail_reasons or []) or "(none)"
                reasoning = (result.raw_response or "")[:1500]
                print(
                    hook_block(
                        _CRITICAL_RETRY_TEMPLATE.format(
                            attempt=count,
                            max_attempts=MAX_RETRIES,
                            reasons=reasons,
                            reasoning=reasoning,
                        )
                    )
                )

    # Telemetry — reuse store created above
    if store is not None:
        try:
            evidence_fragments = {
                "lob": result.lob_evidence,
                "duplication": result.duplication_evidence,
                "type_contract": result.type_contract_evidence,
                "complexity": result.complexity_evidence,
                "naming": result.naming_evidence,
                "spec": result.spec_evidence,
            }
            store.record(
                {
                    "task_id": task_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "session_id": task_id,
                    "oversight_level": oversight_level,
                    "cloud_mode_active": 1
                    if os.environ.get("DEVFLOW_CLOUD_ENDPOINT")
                    else 0,
                    "judge_verdict": verdict,
                    "judge_categories_failed": json.dumps(result.fail_reasons),
                    "judge_reasoning": HarnessJudge.build_reflection_summary(result),
                    "judge_evidence_fragments": json.dumps(evidence_fragments),
                    "lob_violations": 1 if result.lob_violation else 0,
                    "duplication_detected": result.duplication,
                    "type_contract_violations": 1
                    if result.type_contract_violation
                    else 0,
                    "unjustified_complexity": result.unjustified_complexity,
                    "naming_consistency_score": result.naming_consistency_score,
                    "edge_case_coverage": result.edge_case_coverage,
                }
            )
        except Exception as e:
            from _logger import log_error

            log_error(
                "telemetry_record_failed",
                details={
                    "task_id": task_id,
                    "verdict": verdict,
                    "error": f"{type(e).__name__}: {e}",
                },
                hook="post_task_judge",
            )

    return exit_code


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="post_task_judge",
        description=(
            "DevFlow stop-hook judge. When invoked with --session-id, "
            "the emergency-halt + retry state is scoped to that session "
            "(state/{session_id}/emergency-halt.log) instead of the "
            "default hook-resolved path."
        ),
    )
    parser.add_argument(
        "--session-id",
        "--session",
        dest="session_id",
        default=None,
        help="Override session id; scopes state_dir to this session.",
    )
    return parser


def main() -> int:
    if os.environ.get("DEVFLOW_JUDGE_SUBPROCESS") == "1":
        print("[devflow:judge] skipped (subprocess guard)", file=sys.stderr)
        return 0
    args, _ = _build_arg_parser().parse_known_args()
    session_id = args.session_id
    try:
        return run(_get_state_dir(session_id), session_id_override=session_id)
    except Exception as e:
        from _logger import log_error

        log_error(
            "post_task_judge_unexpected",
            details={"error": f"{type(e).__name__}: {e}"},
            hook="post_task_judge",
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
