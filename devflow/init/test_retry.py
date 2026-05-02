"""Tests for devflow.init.retry.RetryController."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.init.retry import RetryController
from devflow.init.runner import ShadowResult
from devflow.init.subagent import FixProposal


@pytest.fixture
def flutter_root(tmp_path: Path) -> Path:
    (tmp_path / "shadow.sh").write_text("#!/bin/bash\nflutter test\n", encoding="utf-8")
    (tmp_path / "Dockerfile.shadow").write_text("FROM scratch\n", encoding="utf-8")
    return tmp_path


def _pass(tmp_path: Path) -> ShadowResult:
    return ShadowResult(rc=0, log_path=tmp_path / "log", duration_s=1.0, verdict_payload={"result": "pass"})


def _sandbox_error(tmp_path: Path) -> ShadowResult:
    return ShadowResult(rc=70, log_path=tmp_path / "log", duration_s=1.0)


def _test_fail(tmp_path: Path) -> ShadowResult:
    return ShadowResult(rc=1, log_path=tmp_path / "log", duration_s=1.0, verdict_payload={"result": "fail"})


def _valid_diff() -> FixProposal:
    diff = (
        "--- a/shadow.sh\n"
        "+++ b/shadow.sh\n"
        "@@ -1,2 +1,2 @@\n"
        " #!/bin/bash\n"
        "-flutter test\n"
        "+flutter test --reporter expanded\n"
    )
    return FixProposal(unified_diff=diff, rationale="r", targets=[Path("shadow.sh")], confidence=0.9)


class TestRetryController:
    def test_returns_immediately_on_first_pass(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        ctrl = RetryController(cap=3)
        with patch("devflow.init.retry.run_shadow", return_value=_pass(flutter_root)):
            out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 0
        assert [a["rc"] for a in attempts] == [0]
        proposer.propose.assert_not_called()

    def test_short_circuits_on_test_fail(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        ctrl = RetryController(cap=3)
        with patch("devflow.init.retry.run_shadow", return_value=_test_fail(flutter_root)):
            out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 1
        assert len(attempts) == 1 and attempts[0]["rc"] == 1
        proposer.propose.assert_not_called()

    def test_retries_on_sandbox_error_up_to_cap(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        proposer.propose.return_value = _valid_diff()
        ctrl = RetryController(cap=3)
        results = [_sandbox_error(flutter_root), _sandbox_error(flutter_root), _sandbox_error(flutter_root), _sandbox_error(flutter_root)]
        with patch("devflow.init.retry.run_shadow", side_effect=results):
            with patch("devflow.init.retry._apply_patch", return_value=True):
                out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 70
        assert proposer.propose.call_count == 3
        # initial + 3 retries recorded
        assert len(attempts) == 4
        assert attempts[-1]["diff_applied"].startswith("--- a/shadow.sh")

    def test_stops_on_first_pass_after_patch(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        proposer.propose.return_value = _valid_diff()
        ctrl = RetryController(cap=3)
        results = [_sandbox_error(flutter_root), _pass(flutter_root)]
        with patch("devflow.init.retry.run_shadow", side_effect=results):
            with patch("devflow.init.retry._apply_patch", return_value=True):
                out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 0
        assert proposer.propose.call_count == 1
        assert [a["rc"] for a in attempts] == [70, 0]

    def test_failed_patch_apply_counts_as_attempt(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        proposer.propose.return_value = _valid_diff()
        ctrl = RetryController(cap=3)
        with patch("devflow.init.retry.run_shadow", return_value=_sandbox_error(flutter_root)):
            with patch("devflow.init.retry._apply_patch", return_value=False):
                out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 70
        assert proposer.propose.call_count == 3
        # initial run + 3 failed-patch attempts (no extra run_shadow)
        assert len(attempts) == 4
        assert all(a["diff_applied"] == "" for a in attempts)

    def test_proposer_returning_none_counts_as_attempt(self, flutter_root: Path) -> None:
        proposer = MagicMock()
        proposer.propose.return_value = None
        ctrl = RetryController(cap=3)
        with patch("devflow.init.retry.run_shadow", return_value=_sandbox_error(flutter_root)):
            out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert out.rc == 70
        assert proposer.propose.call_count == 3
        assert len(attempts) == 4

    def test_token_budget_tripwire(self, flutter_root: Path, monkeypatch, tmp_path: Path) -> None:
        proposer = MagicMock()
        proposer.propose.return_value = _valid_diff()
        state_dir = tmp_path / "state" / "s1"
        state_dir.mkdir(parents=True)
        (state_dir / "tokens-baseline.json").write_text(json.dumps({"total": 200_000, "last_pass": 0}), encoding="utf-8")
        monkeypatch.setenv("DEVFLOW_STATE_DIR", str(tmp_path / "state"))

        ctrl = RetryController(cap=3, token_budget=150_000)
        with patch("devflow.init.retry.run_shadow", return_value=_sandbox_error(flutter_root)) as mock_run_shadow:
            with patch("devflow.init.retry._apply_patch", return_value=True):
                out, attempts = ctrl.run(flutter_root, proposer=proposer, session_id="s1")
        assert (state_dir / "emergency-halt.log").exists()
        assert out.rc == 70
        assert attempts == []  # tripwire fires before any run
        proposer.propose.assert_not_called()
        mock_run_shadow.assert_not_called()

    def test_kb_hits_forwarded_to_proposer(self, flutter_root: Path) -> None:
        from knowledge._types import Node, NodeType
        node = Node(
            id="PATTERN:foo:startup", node_type=NodeType.PATTERN, name="foo",
            summary="s", source_repo="startup", source_path=None, tier=1,
            metadata={}, created_at=0, updated_at=0,
        )
        proposer = MagicMock()
        proposer.propose.return_value = _valid_diff()
        ctrl = RetryController(cap=1)
        results = [_sandbox_error(flutter_root), _sandbox_error(flutter_root)]
        with patch("devflow.init.retry.run_shadow", side_effect=results):
            with patch("devflow.init.retry._apply_patch", return_value=True):
                ctrl.run(flutter_root, proposer=proposer, session_id="s1", kb_hits=[node])
        _, kwargs = proposer.propose.call_args
        assert kwargs["kb_hits"] == [node]
