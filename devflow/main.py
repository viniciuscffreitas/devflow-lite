"""DevFlow CLI entrypoint — emits the OS-level health checks DevFlow expects.

The hermetic shadow-runner binds many concurrent file descriptors (Docker
sidecars, tmpfs overlays, judge SQLite handles). On macOS the default
``ulimit -n`` is 256, which silently caps long sessions and produces
"Too many open files" deep inside Docker — far from the symptom site.

``check_fd_limit`` warns once at import/CLI time so the operator can raise
the limit before a session starts instead of debugging a heisenbug an hour
in. The threshold (4096) matches the soft cap suggested by the V3 sandbox
release notes.
"""
from __future__ import annotations

import resource
import sys

_FD_LIMIT_RECOMMENDED = 4096


def check_fd_limit(stream=sys.stderr) -> bool:
    """Return True when the process FD soft limit is at or above the floor.

    Emits a single-line warning to ``stream`` when below the floor so
    runtime hosts (paperweight, CI) can surface the message in their
    operator channels without parsing structured output.
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return True

    if soft >= _FD_LIMIT_RECOMMENDED:
        return True

    print(
        f"[devflow:os-guard] RLIMIT_NOFILE soft limit is {soft} "
        f"(< {_FD_LIMIT_RECOMMENDED}); raise it before starting long shadow "
        f"sessions, e.g. 'ulimit -n {_FD_LIMIT_RECOMMENDED}'. "
        f"Hard cap is {hard}.",
        file=stream,
    )
    return False


def main() -> int:
    check_fd_limit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
