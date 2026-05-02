"""state_cleanup.py — SessionStart hook.

Prunes stale per-session directories under
~/.claude/devflow-lite/state/<uuid>/ that have not been modified for
longer than STATE_TTL_DAYS. Also trims the freshness cache to a sane
size so it does not grow without bound across hundreds of repos.

Runs once per SessionStart. Cheap (only stats + os.rmtree).
Errors are swallowed — cleanup must never block session start.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".claude/devflow-lite/state"
STATE_TTL_DAYS = 7
STATE_TTL_SECONDS = STATE_TTL_DAYS * 86400

CACHE_FILE = STATE_DIR / "freshness_cache.json"
CACHE_MAX_REPOS = 50
CACHE_REPO_TTL = 7 * 86400


def _looks_like_session_uuid(name: str) -> bool:
    return len(name) == 36 and name.count("-") == 4


def _read_ts(path: Path, key: str) -> float:
    try:
        data = json.loads(path.read_text())
        v = data.get(key, 0)
        return float(v) if isinstance(v, (int, float)) else 0.0
    except (OSError, ValueError, TypeError):
        return 0.0


def _session_last_activity(session_dir: Path) -> float:
    """Most recent recorded timestamp for the session.

    Prefers explicit markers (active-spec.started_at, phase.completed_at)
    so churn inside the dir (dispatcher.log appends) does not artificially
    renew dir mtime and prevent pruning. Falls back to mtime only when no
    markers exist.
    """
    candidates = [
        _read_ts(session_dir / "active-spec.json", "started_at"),
        _read_ts(session_dir / "phase.json", "completed_at"),
    ]
    best = max(candidates)
    if best > 0:
        return best
    try:
        return session_dir.stat().st_mtime
    except OSError:
        return 0.0


def _prune_sessions() -> tuple[int, int]:
    if not STATE_DIR.exists():
        return 0, 0
    now = time.time()
    pruned = 0
    kept = 0
    for entry in STATE_DIR.iterdir():
        if not entry.is_dir():
            continue
        if not _looks_like_session_uuid(entry.name):
            kept += 1
            continue
        last = _session_last_activity(entry)
        if last == 0.0:
            continue
        if now - last > STATE_TTL_SECONDS:
            try:
                shutil.rmtree(entry, ignore_errors=True)
                pruned += 1
            except OSError:
                pass
        else:
            kept += 1
    return pruned, kept


def _trim_freshness_cache() -> int:
    if not CACHE_FILE.exists():
        return 0
    try:
        cache: dict[str, float] = json.loads(CACHE_FILE.read_text())
    except Exception:
        return 0
    if not isinstance(cache, dict):
        return 0
    now = time.time()
    fresh = {
        repo: ts
        for repo, ts in cache.items()
        if isinstance(ts, (int, float)) and now - float(ts) < CACHE_REPO_TTL
    }
    if len(fresh) > CACHE_MAX_REPOS:
        sorted_items = sorted(fresh.items(), key=lambda kv: kv[1], reverse=True)
        fresh = dict(sorted_items[:CACHE_MAX_REPOS])
    if fresh == cache:
        return 0
    removed = len(cache) - len(fresh)
    try:
        tmp = CACHE_FILE.with_suffix(CACHE_FILE.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(fresh))
        os.replace(tmp, CACHE_FILE)
    except OSError:
        return 0
    return removed


def main() -> int:
    try:
        pruned, kept = _prune_sessions()
        cache_dropped = _trim_freshness_cache()
        if pruned or cache_dropped:
            print(
                f"[devflow:state-cleanup] sessions pruned={pruned} kept={kept} "
                f"freshness_cache_dropped={cache_dropped}"
            )
    except Exception as e:
        print(
            f"[devflow:state-cleanup] non-fatal: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
