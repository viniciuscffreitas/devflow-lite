"""DEPRECATED — kept as a no-op for backwards-compatible ops runbooks.

Since 2026-04-24 DevFlow treats Memoria as the authoritative oracle for
curated patterns (PATTERN, TEST_HELPER, TIER1_LESSON). The local SQLite KB
no longer needs to be seeded with those nodes; reads go through
``knowledge.MemoriaOracle`` at runtime.

Existing callers (paperweight image build, ops scripts) keep invoking this
script — we exit 0 with a friendly notice so they do not 404.
"""
from __future__ import annotations

import argparse
import sys


_MSG = (
    "[devflow:kb] Deprecated since 2026-04-24 — Memoria is the authoritative "
    "oracle. This script is a no-op."
)


def main() -> int:
    # Accept (and ignore) the legacy --db flag so existing invocations still
    # parse cleanly.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="(ignored) legacy path flag")
    parser.parse_args()
    print(_MSG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
