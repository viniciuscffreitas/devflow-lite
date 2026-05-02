"""Tests for devflow.init.subagent."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.init.subagent import CompositionFixProposer, FixProposal, _ALLOWED_TARGETS


def _completed(rc: int, stdout: str = "", stderr: str = ""):
    import subprocess
    return subprocess.CompletedProcess(args=["claude"], returncode=rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def proposer() -> CompositionFixProposer:
    return CompositionFixProposer(claude_binary="claude", timeout_s=10)


@pytest.fixture
def valid_payload() -> dict:
    return {
        "unified_diff": "--- a/shadow.sh\n+++ b/shadow.sh\n@@ -1 +1 @@\n-flutter test\n+flutter test --reporter expanded\n",
        "rationale": "need expanded reporter for self-heal",
        "targets": ["shadow.sh"],
        "confidence": 0.8,
    }


class TestCompositionFixProposer:
    def test_returns_proposal_on_happy_path(self, proposer: CompositionFixProposer, tmp_path: Path, valid_payload: dict) -> None:
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, json.dumps(valid_payload))):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert isinstance(out, FixProposal)
        assert out.targets == [Path("shadow.sh")]
        assert out.confidence == 0.8

    def test_rejects_targets_outside_allowlist(self, proposer: CompositionFixProposer, tmp_path: Path, valid_payload: dict) -> None:
        valid_payload["targets"] = ["lib/main.dart"]
        valid_payload["unified_diff"] = "--- a/lib/main.dart\n+++ b/lib/main.dart\n@@\n"
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, json.dumps(valid_payload))):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_rejects_low_confidence(self, proposer: CompositionFixProposer, tmp_path: Path, valid_payload: dict) -> None:
        valid_payload["confidence"] = 0.2
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, json.dumps(valid_payload))):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_rejects_subprocess_nonzero(self, proposer: CompositionFixProposer, tmp_path: Path) -> None:
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(1, "", "claude crashed")):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_rejects_malformed_json(self, proposer: CompositionFixProposer, tmp_path: Path) -> None:
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, "not json")):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_rejects_missing_required_field(self, proposer: CompositionFixProposer, tmp_path: Path, valid_payload: dict) -> None:
        valid_payload.pop("unified_diff")
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, json.dumps(valid_payload))):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_rejects_diff_patching_file_outside_allowlist(self, proposer: CompositionFixProposer, tmp_path: Path, valid_payload: dict) -> None:
        valid_payload["unified_diff"] = (
            "--- a/shadow.sh\n+++ b/shadow.sh\n@@ -1 +1 @@\n-x\n+y\n"
            "--- a/lib/main.dart\n+++ b/lib/main.dart\n@@ -1 +1 @@\n-a\n+b\n"
        )
        with patch("devflow.init.subagent.subprocess.run", return_value=_completed(0, json.dumps(valid_payload))):
            out = proposer.propose(root=tmp_path, shadow_log="err", kb_hits=[], attempt=1, max_attempts=3)
        assert out is None

    def test_allowlist_contains_expected_files(self) -> None:
        assert _ALLOWED_TARGETS == frozenset({"shadow.sh", "Dockerfile.shadow", "sandbox.yaml", "sandbox.lock.yaml"})
