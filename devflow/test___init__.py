"""Tests for the top-level `devflow` SDK namespace."""
from __future__ import annotations

import importlib


def test_namespace_importable():
    devflow = importlib.import_module("devflow")
    assert hasattr(devflow, "__version__")


def test_public_surface_present():
    import devflow
    expected = {
        "KnowledgeProvider",
        "KnowledgeStore",
        "Node",
        "Edge",
        "NodeType",
        "Relation",
        "kb_enabled",
        "governance_bridge",
        "__version__",
    }
    assert expected.issubset(set(devflow.__all__))
    for name in expected:
        assert hasattr(devflow, name), f"devflow.{name} missing"


def test_governance_bridge_callable():
    from devflow import governance_bridge
    assert callable(governance_bridge)
    # Error-payload path (no state_dir) is pure; safe to exercise.
    out = governance_bridge({})
    assert out["status"] == "error"


def test_knowledge_provider_open_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DEVFLOW_KB_ENABLED", raising=False)
    from devflow import KnowledgeProvider
    kp = KnowledgeProvider.open(path=tmp_path / "kb.db")
    try:
        assert kp.enabled is False
    finally:
        kp.close()
