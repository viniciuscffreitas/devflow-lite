"""DevFlow Lite — slim guardrail harness for Claude Code.

This top-level namespace used to expose a Knowledge-Base SDK; that surface
lives in the full devflow product, not in lite. Lite ships only hooks and
the FD-limit checker (``devflow.main.check_fd_limit``).
"""

from __future__ import annotations

__version__ = "0.2.1"

__all__ = ["__version__"]
