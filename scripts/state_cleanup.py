#!/usr/bin/env python3.13
"""
State directory cleanup — removes session state dirs older than N days.

Usage:
  python3.13 scripts/state_cleanup.py              # dry-run (default)
  python3.13 scripts/state_cleanup.py --apply       # actually delete
  python3.13 scripts/state_cleanup.py --max-age 14  # override age threshold
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _paths import current_paths  # noqa: E402

_PRESERVE = {"default"}  # never delete these


def cleanup_state(
    state_dir: Path,
    max_age_days: int = 7,
    dry_run: bool = False,
) -> int:
    """Remove session state directories older than max_age_days.

    Returns the number of directories removed (or that would be removed in dry_run).
    """
    if not state_dir.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for entry in state_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in _PRESERVE:
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            if not dry_run:
                shutil.rmtree(entry, ignore_errors=True)
            removed += 1

    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean up stale devflow state directories")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default is dry-run)")
    parser.add_argument("--max-age", type=int, default=7, dest="max_age", help="Max age in days (default: 7)")
    args = parser.parse_args(argv)

    dry_run = not args.apply
    removed = cleanup_state(current_paths().state, max_age_days=args.max_age, dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"[devflow:cleanup] {mode} | {removed} directories {'would be ' if dry_run else ''}removed (>{args.max_age} days)")

    if dry_run and removed > 0:
        print("  Run with --apply to actually delete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
