"""DevFlow SDK — public Python surface.

External consumers (paperweight, custom CI shims, editor integrations)
should import from this top-level namespace instead of reaching into the
internal ``knowledge``/``hooks``/``mcp`` modules directly. This keeps
the promise of stable names even when internals move.

Typical usage::

    from devflow import KnowledgeProvider

    with KnowledgeProvider.open(force_enabled=True) as kp:
        for node in kp.query("Upsert-on-Heal"):
            print(node.name, node.source_path)

The governance bridge (stdin/stdout adapter used by paperweight's HTTP
backend) is exposed as ``devflow.governance_bridge``::

    from devflow import governance_bridge
    result = governance_bridge({"state_dir": "/tmp/state"})
"""
from __future__ import annotations

from knowledge import (
    Edge,
    KnowledgeProvider,
    KnowledgeStore,
    Node,
    NodeType,
    Relation,
    kb_enabled,
)
from hooks.paperweight_bridge import bridge as governance_bridge

__version__ = "0.2.0"

__all__ = [
    "KnowledgeProvider",
    "KnowledgeStore",
    "Node",
    "Edge",
    "NodeType",
    "Relation",
    "kb_enabled",
    "governance_bridge",
    "__version__",
]
