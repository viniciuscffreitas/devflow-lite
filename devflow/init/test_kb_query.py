"""Tests for devflow.init.kb_query."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from devflow.init.detector import Stack
from devflow.init.kb_query import _STACK_QUERY, ensure_kb_seeded, query_patterns_for_stack


def _node(name: str, **overrides):
    from knowledge._types import Node, NodeType
    return Node(
        id=f"PATTERN:{name}:startup",
        node_type=NodeType.PATTERN,
        name=name,
        summary=overrides.get("summary", "s"),
        source_repo=overrides.get("source_repo", "startup"),
        source_path=None,
        tier=overrides.get("tier", 1),
        metadata={},
        created_at=0,
        updated_at=0,
    )


class TestEnsureKbSeeded:
    """Post-2026-04-24: ``ensure_kb_seeded`` reads from the oracle — it does
    not seed. True iff the oracle exposes ≥ threshold Tier-1 nodes for the
    requested source_repo.
    """

    def _make_kp(self, nodes):
        kp = MagicMock()
        kp.tier1_patterns.return_value = nodes
        # Context-manager shim.
        kp.__enter__.return_value = kp
        kp.__exit__.return_value = False
        return kp

    def test_true_when_oracle_meets_threshold(self, tmp_path: Path) -> None:
        kp = self._make_kp([_node(f"p{i}") for i in range(12)])
        with patch("devflow.init.kb_query.KnowledgeProvider.open", return_value=kp):
            assert ensure_kb_seeded(threshold=8, db_path=tmp_path / "kb.sqlite") is True
            kp.tier1_patterns.assert_called_once_with(source_repo="startup")

    def test_false_when_oracle_below_threshold(self, tmp_path: Path) -> None:
        kp = self._make_kp([_node(f"p{i}") for i in range(3)])
        with patch("devflow.init.kb_query.KnowledgeProvider.open", return_value=kp):
            assert ensure_kb_seeded(threshold=8, db_path=tmp_path / "kb.sqlite") is False

    def test_false_when_oracle_raises(self, tmp_path: Path) -> None:
        with patch(
            "devflow.init.kb_query.KnowledgeProvider.open",
            side_effect=RuntimeError("memoria down"),
        ):
            assert ensure_kb_seeded(threshold=8, db_path=tmp_path / "kb.sqlite") is False

    def test_source_repo_filter_passed_through(self, tmp_path: Path) -> None:
        kp = self._make_kp([])
        with patch("devflow.init.kb_query.KnowledgeProvider.open", return_value=kp):
            ensure_kb_seeded(threshold=1, db_path=tmp_path / "kb.sqlite", source_repo="otherrepo")
            kp.tier1_patterns.assert_called_once_with(source_repo="otherrepo")


class TestQueryPatternsForStack:
    def test_dispatches_correct_fts_query_per_stack(self) -> None:
        kp = MagicMock()
        kp.query.return_value = [_node("UpsertOnHeal")]
        result = query_patterns_for_stack(kp, Stack.FLUTTER, top_k=5)
        kp.query.assert_called_once_with(_STACK_QUERY[Stack.FLUTTER], top_k=5)
        assert [n.name for n in result] == ["UpsertOnHeal"]

    def test_empty_when_kp_disabled(self) -> None:
        kp = MagicMock()
        kp.query.return_value = []
        assert query_patterns_for_stack(kp, Stack.FLUTTER) == []

    def test_each_stack_has_query_string(self) -> None:
        for stack in Stack:
            assert stack in _STACK_QUERY, f"missing FTS query for {stack}"
            assert _STACK_QUERY[stack], f"empty FTS query for {stack}"
