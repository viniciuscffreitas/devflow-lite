"""Session ID resolution for devflow hooks.

SessionProvider is the class-based API for dependency injection (MCP server,
tests). Module-level `get_session_id`/`is_safe_session` delegate to a shared
provider for backward compatibility with ~40 existing callsites.
"""
from __future__ import annotations

import os
import sys


class SessionProvider:
    """Resolve session identity from env vars or stdin, with pid fallback.

    Priority:
      1. CLAUDE_SESSION_ID  — env var set by Claude Code.
      2. DEVFLOW_SESSION_ID — manual override (MCP server, scripts, tests).
      3. stdin session_id   — hook JSON payload (when env absent).
      4. pid-{os.getpid()}  — last resort; increments pid-fallback counter so
                              operators see the drift instead of silent dir
                              explosion (diagnostic 2026-04-21: 249 dirs,
                              docstring-alerted 138k risk).
    """

    def get_session_id(self) -> str:
        if sid := os.environ.get("CLAUDE_SESSION_ID"):
            return sid
        if sid := os.environ.get("DEVFLOW_SESSION_ID"):
            return sid
        try:
            from _stdin_cache import get as _stdin
            if sid := _stdin().get("session_id"):
                return sid
        except Exception:
            pass
        self._bump_pid_fallback_counter()
        return f"pid-{os.getpid()}"

    def is_safe_session(self) -> bool:
        """True only when a stable, isolation-safe session ID is available.

        Honors both CLAUDE_SESSION_ID (hook-supplied) and DEVFLOW_SESSION_ID
        (MCP/test injection). Mirrors get_session_id priority so state_dir
        never collapses an injected stable id into "default".
        """
        raw = os.environ.get("CLAUDE_SESSION_ID", "").strip()
        if raw and raw != "default":
            return True
        devflow = os.environ.get("DEVFLOW_SESSION_ID", "").strip()
        return bool(devflow) and devflow != "default"

    def _bump_pid_fallback_counter(self) -> None:
        """Append to counter file — one source of truth for pid-explosion risk."""
        try:
            from _paths import current_paths
            log_dir = current_paths().errors_log
            log_dir.mkdir(parents=True, exist_ok=True)
            counter = log_dir / "pid-fallback.count"
            current = 0
            if counter.exists():
                try:
                    current = int(counter.read_text().strip() or "0")
                except ValueError:
                    current = 0
            counter.write_text(str(current + 1))
        except OSError:
            print("[devflow:_session] pid-fallback counter write failed", file=sys.stderr)


_default_provider = SessionProvider()


def get_session_id() -> str:
    return _default_provider.get_session_id()


def is_safe_session() -> bool:
    return _default_provider.is_safe_session()
