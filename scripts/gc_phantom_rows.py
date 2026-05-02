#!/usr/bin/env python3
"""Garbage-collect phantom rows from the devflow telemetry DB.

Phantom rows: task_executions entries where judge_verdict IS NULL AND
timestamp IS NULL. Historically written by PreToolUse hooks
(pre_task_profiler, pre_task_firewall) when the session never reached a Stop
hook (subprocess invocation, early exit, crash). After the timestamp fix in
those hooks, new sessions no longer produce phantoms; this script cleans the
pre-fix backlog.

Dry-run by default: prints the count and sample IDs, does NOT delete. Pass
`--apply` to actually run the DELETE. Exit 0 on success.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _paths import current_paths  # noqa: E402


def _default_db() -> Path:
    return current_paths().telemetry / "devflow.db"

_PHANTOM_WHERE = "judge_verdict IS NULL AND timestamp IS NULL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="Path to devflow.db")
    parser.add_argument("--apply", action="store_true", help="Actually DELETE (default: dry-run)")
    args = parser.parse_args()
    if args.db is None:
        args.db = _default_db()

    if not args.db.exists():
        print(f"[gc] db not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db))
    try:
        cur = conn.cursor()
        total = cur.execute(
            f"SELECT COUNT(*) FROM task_executions WHERE {_PHANTOM_WHERE}"
        ).fetchone()[0]
        print(f"[gc] phantom rows found: {total}")
        if total == 0:
            return 0

        sample = cur.execute(
            f"SELECT task_id FROM task_executions WHERE {_PHANTOM_WHERE} LIMIT 5"
        ).fetchall()
        for (tid,) in sample:
            print(f"  - {tid}")

        if not args.apply:
            print("[gc] dry-run — pass --apply to delete")
            return 0

        cur.execute(f"DELETE FROM task_executions WHERE {_PHANTOM_WHERE}")
        conn.commit()
        print(f"[gc] deleted {cur.rowcount} rows")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
