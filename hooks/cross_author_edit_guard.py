"""cross_author_edit_guard.py — PreToolUse Edit/Write/MultiEdit hook.

Blocks the *first* attempt to edit a file that another author committed
recently (default: last 7 days). Records the path in a per-session ack
file; the second attempt to edit the same path passes silently. The
intent is to force a single pause + look at upstream work, not to make
the user fight the hook to do their job.

Complements pre_edit_overwrite_guard:
  - overwrite_guard fires only when HEAD is behind upstream for the file
  - cross_author guard fires even when HEAD is in sync, as long as the
    last commit on the file is by another author within the window

This catches the daily 2026-04-29 case: Maria pushes, Vinicius pulls
(now in sync), Vinicius edits without realising Maria touched it.

Override:
  - Re-trigger the same edit (second attempt within session passes)
  - DEVFLOW_OVERRIDE_CROSS_AUTHOR=1 for batch ops
  - disabled_hooks: ["cross_author_edit_guard"] in devflow-config.json
  - Window configurable via cross_author_window_days (default 7)

Exit 0 always for non-Edit tools, non-git paths, self-authored files,
files outside the window, or after ack. Exit 2 only on the first hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _session import get_session_id, is_safe_session
from _util import is_hook_disabled, load_devflow_config, read_hook_stdin

HOOK_NAME = "cross_author_edit_guard"
DEFAULT_WINDOW_DAYS = 7
GIT_TIMEOUT = 4
OVERRIDE_ENV = "DEVFLOW_OVERRIDE_CROSS_AUTHOR"

_ACK_BASE = Path.home() / ".claude" / "devflow-lite" / "state"


def _git(*args: str, cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            cwd=cwd,
            check=False,
        )
        return out.stdout
    except Exception:
        return ""


def _ack_path(session_id: str, repo: str, rel: str) -> Path:
    sid = session_id if is_safe_session() else "default"
    key = hashlib.sha256(f"{repo}\x00{rel}".encode()).hexdigest()[:16]
    return _ACK_BASE / sid / "cross-author-ack" / f"{key}.json"


def _record_ack(path: Path, repo: str, rel: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"repo": repo, "rel": rel, "ts": int(time.time())}))
        return True
    except OSError:
        return False


def _block(rel: str, author: str, age_days: int, sha: str) -> int:
    print(
        f"[devflow:cross-author-guard] BLOCK: '{rel}' last edited "
        f"{age_days}d ago by {author} (commit {sha[:8]})",
        file=sys.stderr,
    )
    print(
        f"  inspect: git log -1 -p -- {rel}\n"
        "  retry the same edit to acknowledge and proceed (per-session)\n"
        f"  bypass batch ops: {OVERRIDE_ENV}=1\n"
        "  disable for repo: add 'cross_author_edit_guard' to disabled_hooks "
        "in .devflow-config.json",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if is_hook_disabled(HOOK_NAME):
        return 0
    if os.environ.get(OVERRIDE_ENV) == "1":
        return 0

    payload = read_hook_stdin()
    if not payload:
        return 0
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    repo = _git("rev-parse", "--show-toplevel", cwd=cwd).strip()
    if not repo:
        return 0

    if is_hook_disabled(HOOK_NAME, Path(repo)):
        return 0

    cfg = load_devflow_config(Path(repo))
    window_days = int(cfg.get("cross_author_window_days", DEFAULT_WINDOW_DAYS))

    try:
        rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(repo))
    except ValueError:
        return 0
    if rel.startswith("..") or os.path.isabs(rel):
        return 0

    head_check = _git("rev-parse", "--verify", "-q", "HEAD", cwd=repo).strip()
    if not head_check:
        return 0

    raw = _git(
        "log",
        "-1",
        "--format=%H%x09%ae%x09%an%x09%at",
        "--",
        rel,
        cwd=repo,
    ).strip()
    if not raw:
        return 0

    parts = raw.split("\t")
    if len(parts) != 4:
        return 0
    sha, author_email, author_name, author_ts = parts

    me_email = _git("config", "user.email", cwd=repo).strip()
    if not me_email:
        return 0
    if author_email == me_email:
        return 0

    try:
        ts = int(author_ts)
    except ValueError:
        return 0
    age_days = (int(time.time()) - ts) // 86400
    if age_days >= window_days:
        return 0

    session_id = get_session_id()
    ack = _ack_path(session_id, repo, rel)
    if ack.exists():
        return 0

    if not _record_ack(ack, repo, rel):
        print(
            f"[devflow:cross-author-guard] WARN: could not write ack at {ack}; "
            f"retry will re-trigger. Use {OVERRIDE_ENV}=1 if needed.",
            file=sys.stderr,
        )
    return _block(rel, author_name, age_days, sha)


if __name__ == "__main__":
    sys.exit(main())
