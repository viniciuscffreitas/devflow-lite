"""``devflow init`` — agentic bootstrap CLI (thin wrapper).

Real logic lives in devflow.init.run_init. Keeping the module path
``scripts.devflow_init:main`` preserves the pyproject console script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from devflow.init import run_init


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devflow-init")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--kb-seed-threshold", type=int, default=8, dest="kb_seed_threshold")
    parser.add_argument("--session-id", dest="session_id", default=None)
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args(argv)

    return run_init(
        Path(args.path),
        retries=args.retries,
        kb_seed_threshold=args.kb_seed_threshold,
        session_id=args.session_id,
        undo=args.undo,
    )


if __name__ == "__main__":
    sys.exit(main())
