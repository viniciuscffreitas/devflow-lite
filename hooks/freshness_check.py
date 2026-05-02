"""freshness_check.py — SessionStart hook.

Runs `git fetch` once at session start and emits a status block describing
how the current branch relates to its upstream. Pairs with
`pre_edit_overwrite_guard.py` which uses the cached fetch to block edits
that would overwrite remote work.

Output is informational on SessionStart (advisory). The hard block lives
in the per-edit guard.

Cache file: ~/.claude/devflow-lite/state/freshness_cache.json
  Format: {"<repo_root>": <unix_ts_of_last_fetch>}
  TTL: 300s — pre_edit_overwrite_guard re-fetches on miss.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path.home() / ".claude/devflow-lite/state/freshness_cache.json"
FETCH_TIMEOUT = 10
DEFAULT_FETCH_TTL = 300


def _last_fetch(repo: str) -> float:
    if not CACHE.exists():
        return 0.0
    try:
        cache = json.loads(CACHE.read_text())
        return float(cache.get(repo, 0))
    except Exception:
        return 0.0


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _record_fetch(repo: str) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, float] = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text())
        except Exception:
            cache = {}
    cache[repo] = time.time()
    try:
        tmp = CACHE.with_suffix(CACHE.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, CACHE)
    except OSError:
        pass


def main() -> int:
    cwd = os.environ.get("DEVFLOW_LITE_CWD") or os.getcwd()
    repo = _git("rev-parse", "--show-toplevel", cwd=cwd)
    if not repo:
        return 0

    ttl = DEFAULT_FETCH_TTL
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from _util import is_hook_disabled, load_devflow_config

        if is_hook_disabled("freshness_check"):
            return 0
        ttl = int(
            load_devflow_config(Path(repo)).get(
                "freshness_fetch_ttl", DEFAULT_FETCH_TTL
            )
        )
    except Exception:
        pass

    age = time.time() - _last_fetch(repo)
    if age < ttl:
        # Cache fresh — skip fetch but still emit upstream status from local refs.
        pass
    else:
        try:
            subprocess.run(
                ["git", "fetch", "--quiet"],
                cwd=repo,
                timeout=FETCH_TIMEOUT,
                check=False,
                capture_output=True,
            )
        except Exception:
            pass
        _record_fetch(repo)

    upstream = _git("rev-parse", "--abbrev-ref", "@{u}", cwd=repo)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if not upstream:
        print(f"[devflow:freshness] branch={branch} upstream=none (no tracking branch)")
        return 0

    behind = _git("rev-list", "--count", f"HEAD..{upstream}", cwd=repo) or "0"
    ahead = _git("rev-list", "--count", f"{upstream}..HEAD", cwd=repo) or "0"

    print(
        f"[devflow:freshness] branch={branch} upstream={upstream} behind={behind} ahead={ahead}"
    )
    if int(behind) > 0:
        files_behind = _git(
            "log", f"HEAD..{upstream}", "--name-only", "--format=", cwd=repo
        )
        files = sorted({f for f in files_behind.splitlines() if f.strip()})
        sample = ", ".join(files[:5]) + (
            f", +{len(files) - 5} more" if len(files) > 5 else ""
        )
        print(f"[devflow:freshness] WARN: {behind} commits behind {upstream}")
        print(f"  files modified upstream: {sample}")
        print(
            "  edit those files = BLOCKED until 'git pull --rebase' (or merge upstream)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
