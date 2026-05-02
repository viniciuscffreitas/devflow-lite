"""Stack detection for devflow-init.

Ordered heuristic over well-known marker files. The order IS the contract:
Python > Node > Flutter > Rust > Go > generic. If a project has multiple
marker files (polyrepo / monorepo), the first match wins. This matches the
existing behavior of ``scripts/devflow_init.py`` with Flutter slotted in
between Node and Rust — Flutter projects with a Python tools dir at the
root (common for scripts/) still get the Python treatment, which is the
less surprising choice for the user running ``devflow-init`` there.
"""
from __future__ import annotations

import enum
from pathlib import Path


class Stack(enum.StrEnum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"
    GO = "go"
    FLUTTER = "flutter"
    GENERIC = "generic"


_DETECTORS: list[tuple[Stack, tuple[str, ...]]] = [
    (Stack.PYTHON, ("pyproject.toml", "requirements.txt")),
    (Stack.NODE, ("package.json",)),
    (Stack.FLUTTER, ("pubspec.yaml",)),
    (Stack.RUST, ("Cargo.toml",)),
    (Stack.GO, ("go.mod",)),
]


def detect_stack(root: Path) -> Stack:
    for stack, markers in _DETECTORS:
        for marker in markers:
            if (root / marker).exists():
                return stack
    return Stack.GENERIC
