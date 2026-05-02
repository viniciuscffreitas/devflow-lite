"""test_deletion_guard.py — PreToolUse Bash hook.

Hard block on `git commit` when staged diff deletes a test file. Designed
for low friction: only fires on full deletion (status=D), not on shrink
or refactor. Override via Override-Test-Deletion trailer in commit message
or DEVFLOW_OVERRIDE_TEST_DELETION env var.

Closes the gap from devflow-lite's pre_push_gate (which only catches the
break if the deleted test was actually relied on by remaining tests).
Stops "Claude rewrote the feature and pruned its own test suite while at
it" — the daily 2026-04-29 case.

Patterns recognised:
  Python   test_*.py, *_test.py
  JS/TS    *.test.ts, *.test.tsx, *.test.js, *.spec.ts, *.spec.js
  Go       *_test.go
  Dart     *_test.dart, paths under test/
  Ruby     *_spec.rb, *_test.rb
  Rust     paths under tests/
  Kotlin   *Test.kt, *Spec.kt

Exit 0 always for non-commit commands, non-git paths, when no test file
deleted, when override is present, or when hook is disabled via config.
Exit 2 only when a test file deletion is staged without override.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import is_hook_disabled, read_hook_stdin

HOOK_NAME = "test_deletion_guard"
GIT_TIMEOUT = 4
OVERRIDE_TRAILER = "Override-Test-Deletion"
OVERRIDE_ENV = "DEVFLOW_OVERRIDE_TEST_DELETION"

_GIT_COMMIT_RE = re.compile(r"^\s*git\s+commit(\s|$)")

_TEST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
    re.compile(r"(^|/)[^/]+\.test\.(ts|tsx|js|jsx|mjs|cjs)$"),
    re.compile(r"(^|/)[^/]+\.spec\.(ts|tsx|js|jsx|mjs|cjs|rb)$"),
    re.compile(r"(^|/)[^/]+_test\.go$"),
    re.compile(r"(^|/)[^/]+_test\.dart$"),
    re.compile(r"^test/.+\.dart$"),
    re.compile(r"(^|/)[^/]+_(spec|test)\.rb$"),
    re.compile(r"^tests/.+\.rs$"),
    re.compile(r"(^|/)[^/]+(Test|Spec)\.kt$"),
)


def _is_test_path(rel: str) -> bool:
    return any(p.search(rel) for p in _TEST_PATTERNS)


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


def _staged_deletions(repo: str) -> list[str]:
    raw = _git("diff", "--cached", "--name-status", "--no-renames", cwd=repo)
    deletions: list[str] = []
    for line in raw.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts[0].strip(), parts[1].strip()
        if status == "D" and _is_test_path(path):
            deletions.append(path)
    return deletions


def _commit_message_text(cmd: str, cwd: str) -> str:
    """Best-effort extraction of the commit message text from a `git commit`
    command line. Looks for `-m <msg>`, `-m=<msg>`, `--message=<msg>`,
    `-F <file>`, `--file=<file>`. Returns concatenation of all sources."""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return ""
    parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-m", "--message") and i + 1 < len(tokens):
            parts.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("-m="):
            parts.append(tok[3:])
            i += 1
            continue
        if tok.startswith("--message="):
            parts.append(tok[len("--message="):])
            i += 1
            continue
        if tok in ("-F", "--file") and i + 1 < len(tokens):
            path = tokens[i + 1]
            parts.append(_read_file_safe(path, cwd))
            i += 2
            continue
        if tok.startswith("--file="):
            parts.append(_read_file_safe(tok[len("--file="):], cwd))
            i += 1
            continue
        i += 1
    return "\n".join(parts)


def _read_file_safe(path: str, cwd: str) -> str:
    try:
        p = Path(path)
        if not p.is_absolute():
            p = Path(cwd) / p
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_override_trailer(message: str) -> bool:
    pattern = re.compile(rf"^\s*{re.escape(OVERRIDE_TRAILER)}\s*:\s*\S+", re.MULTILINE)
    return bool(pattern.search(message))


def _block(deletions: list[str]) -> int:
    listed = "\n".join(f"  - {p}" for p in deletions)
    print(
        "[devflow:test-deletion-guard] BLOCK: commit deletes test file(s):\n"
        f"{listed}\n"
        "  fix (recommended): unstage with `git restore --staged <file>` and keep the suite\n"
        f"  override (if intentional): add a trailer to the commit message:\n"
        f"      {OVERRIDE_TRAILER}: <reason — what replaces the coverage>\n"
        f"  or set {OVERRIDE_ENV}=1 for a one-shot bypass",
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
    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not _GIT_COMMIT_RE.match(command):
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    repo = _git("rev-parse", "--show-toplevel", cwd=cwd).strip()
    if not repo:
        return 0

    project_config = Path(repo) / ".devflow-config.json"
    if project_config.exists() and is_hook_disabled(HOOK_NAME, Path(repo)):
        return 0

    deletions = _staged_deletions(repo)
    if not deletions:
        return 0

    message = _commit_message_text(command, cwd)
    if _has_override_trailer(message):
        return 0

    return _block(deletions)


if __name__ == "__main__":
    sys.exit(main())
