"""branch_policy.py — PreToolUse Bash hook.

Blocks pushes that violate team workflow:
  - direct push to main/master/develop/release/* (blocked unless allow_push_to_main=true)
  - force-push to a branch you do not own (blocked unless --force-with-lease and you authored last commit)
  - non-conventional branch name on push -u (warn only)

Project override: set {"allow_push_to_main": true} in .devflow-config.json to permit
direct pushes to main (e.g. solo repos with 100% autonomy granted).

Exit codes: 0 ok, 2 block (Claude Code surfaces stderr).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import load_devflow_config, read_hook_stdin


PROTECTED = re.compile(r"^(main|master|develop|release/.*|hotfix/.*)$")
VALID_PREFIX = re.compile(
    r"^(feat|fix|chore|docs|refactor|test|perf|ci|build)/[\w\-/]+$"
)


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=cwd,
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _block(msg: str) -> None:
    print(f"[devflow:branch-policy] BLOCK: {msg}", file=sys.stderr)
    sys.exit(2)


def _warn(msg: str) -> None:
    print(f"[devflow:branch-policy] WARN: {msg}")


def _parse_push_target(cmd: str) -> tuple[str, str]:
    """Extract (remote, branch) from a git push command, ignoring flags."""
    after_push = cmd.split("git push", 1)[1] if "git push" in cmd else ""
    tokens = [t for t in after_push.split() if not t.startswith("-")]
    if len(tokens) >= 2:
        return tokens[0], tokens[1].split(":")[0]
    if len(tokens) == 1:
        return tokens[0], ""
    return "", ""


def main() -> int:
    payload = read_hook_stdin()
    cmd = (payload.get("tool_input", {}) or {}).get("command", "")
    cwd = payload.get("cwd")
    if not cmd or "git push" not in cmd:
        return 0

    cfg = load_devflow_config(Path(cwd) if cwd else None)
    allow_push_to_main: bool = bool(cfg.get("allow_push_to_main", False))

    _, target = _parse_push_target(cmd)
    current = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd) or target
    branch = target or current

    if PROTECTED.match(branch) and not allow_push_to_main:
        _block(f"push to protected branch '{branch}' is forbidden — open a PR")

    if "--force" in cmd and "--force-with-lease" not in cmd:
        _block("plain --force is forbidden — use --force-with-lease")

    if "--force" in cmd or "--force-with-lease" in cmd:
        author = _git("log", "-1", "--format=%ae", cwd=cwd)
        me = _git("config", "user.email", cwd=cwd)
        if author and me and author != me:
            _block(f"force-push to branch with last commit by {author} (not you: {me})")

    if "-u" in cmd or "--set-upstream" in cmd:
        if not VALID_PREFIX.match(branch):
            _warn(f"branch '{branch}' lacks conventional prefix (feat/fix/chore/...)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
