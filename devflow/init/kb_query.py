"""Knowledge Base integration for devflow-init.

Since 2026-04-24 the KB is an oracle (Memoria-backed by default), not a
seeded local SQLite. ``ensure_kb_seeded`` preserves its legacy name for
callers, but its implementation now asks the oracle for reachable Tier-1
patterns — no subprocess, no seeding side-effect.
"""
from __future__ import annotations

from pathlib import Path

from knowledge._types import Node
from knowledge.provider import KnowledgeProvider

from devflow.init.detector import Stack

_STACK_QUERY: dict[Stack, str] = {
    Stack.FLUTTER: "flutter OR dart OR bloc OR widget",
    Stack.PYTHON: "pytest OR mock OR fixture",
    Stack.NODE: "jest OR npm OR vitest",
    Stack.RUST: "cargo OR tokio",
    Stack.GO: "go test OR table driven",
    Stack.GENERIC: "tier1 OR test",
}


def ensure_kb_seeded(
    *,
    threshold: int = 8,
    db_path: Path | None = None,
    source_repo: str = "startup",
) -> bool:
    """Return True iff the oracle knows ≥ ``threshold`` Tier-1 nodes for
    ``source_repo``. Never raises — degrades to False when the oracle is
    unreachable so callers can choose to proceed with empty patterns.
    """
    try:
        with KnowledgeProvider.open(path=db_path, force_enabled=True) as kp:
            nodes = kp.tier1_patterns(source_repo=source_repo)
            return len(nodes) >= threshold
    except Exception:
        return False


def query_patterns_for_stack(
    kp: KnowledgeProvider,
    stack: Stack,
    *,
    top_k: int = 10,
) -> list[Node]:
    """Stack-aware FTS query, routed through the active oracle."""
    query = _STACK_QUERY[stack]
    return kp.query(query, top_k=top_k)
