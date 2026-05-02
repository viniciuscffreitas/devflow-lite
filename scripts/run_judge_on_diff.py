"""
CLI entry point for PR-gate judge run.

Usage:
  python scripts/run_judge_on_diff.py --base origin/main

Exits 0 (learning mode). Prints summary to stdout for PR comment.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from judge.evaluator import HarnessJudge, JudgePayload


def _diff(base: str) -> str | None:
    """Return diff text, or None if git invocation failed."""
    proc = subprocess.run(
        ["git", "diff", f"{base}...HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        print(
            f"git diff failed (exit {proc.returncode}): {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return proc.stdout or ""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="origin/main", help="Base ref for diff")
    args = p.parse_args()

    diff = _diff(args.base)
    if diff is None:
        print("git diff unavailable — skipping judge")
        return 0
    if not diff.strip():
        print("no diff — nothing to judge")
        return 0

    payload = JudgePayload(
        diff=diff,
        spec="PR gate — evaluate final state of this diff against business intent.",
        harness_rules=[
            "fail on monetary_math=broken, contract=breaking, user_intent=no",
            "warn on idempotency=broken or user_intent=partial",
        ],
        existing_code="(not provided in PR-gate mode)",
        feature_path=".",
        task_id=f"pr-gate-{args.base}",
    )
    result = HarnessJudge().evaluate(payload)

    print(f"verdict={result.verdict}")
    print(f"monetary_math_status={result.monetary_math_status}")
    print(f"idempotency_status={result.idempotency_status}")
    print(f"contract_status={result.contract_status}")
    print(f"user_intent_status={result.user_intent_status}")
    if result.fail_reasons:
        print("fail_reasons:", ", ".join(result.fail_reasons))
    return 0  # learning mode: never block


if __name__ == "__main__":
    sys.exit(main())
