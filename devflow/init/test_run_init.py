"""Tests for devflow.init.run_init orchestration."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.init import run_init
from devflow.init.runner import ShadowResult


def _pass(tmp_path: Path) -> ShadowResult:
    return ShadowResult(rc=0, log_path=tmp_path / "log", duration_s=0.1, verdict_payload={"result": "pass"})


@pytest.fixture
def flutter_project(tmp_path: Path) -> Path:
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    return tmp_path


class TestRunInit:
    def test_happy_path_returns_0(self, flutter_project: Path) -> None:
        with patch("devflow.init.ensure_kb_seeded", return_value=True):
            with patch("devflow.init.KnowledgeProvider") as kp_cls:
                kp_cls.open.return_value.__enter__.return_value.query.return_value = []
                with patch("devflow.init.RetryController") as rc_cls:
                    rc_cls.return_value.run.return_value = (_pass(flutter_project), [])
                    rc = run_init(flutter_project, retries=3, kb_seed_threshold=1, session_id="s1")
        assert rc == 0
        assert (flutter_project / "shadow.sh").exists()
        assert (flutter_project / "Dockerfile.shadow").exists()
        assert (flutter_project / ".devflow" / "init-manifest.json").exists()

    def test_exit_non_zero_on_final_fail(self, flutter_project: Path, monkeypatch, tmp_path: Path) -> None:
        state_root = tmp_path / "state"
        monkeypatch.setenv("DEVFLOW_STATE_DIR", str(state_root))
        final = ShadowResult(rc=70, log_path=flutter_project / "log", duration_s=0.1)
        attempts = [
            {"attempt": 0, "rc": 70, "log_tail": "boom", "diff_applied": ""},
            {"attempt": 1, "rc": 70, "log_tail": "boom again", "diff_applied": "--- a/shadow.sh\n"},
        ]
        with patch("devflow.init.ensure_kb_seeded", return_value=True):
            with patch("devflow.init.KnowledgeProvider") as kp_cls:
                kp_cls.open.return_value.__enter__.return_value.query.return_value = []
                with patch("devflow.init.RetryController") as rc_cls:
                    rc_cls.return_value.run.return_value = (final, attempts)
                    rc = run_init(flutter_project, retries=3, kb_seed_threshold=1, session_id="s1")
        assert rc == 1
        post = (state_root / "s1" / "init-post-mortem.md").read_text(encoding="utf-8")
        assert "Attempts: 2" in post
        assert "boom again" in post

    def test_undo_path_delegates_to_manifest(self, flutter_project: Path) -> None:
        from devflow.init.manifest import ArtifactEntry, InitManifest
        (flutter_project / "shadow.sh").write_text("ok\n", encoding="utf-8")
        m = InitManifest(
            created_at=1, stack="flutter", session_id="s1",
            artifacts=[ArtifactEntry(path="shadow.sh", sha256=hashlib.sha256(b"ok\n").hexdigest())],
            git_hook_backup=None,
        )
        m.save(flutter_project)
        rc = run_init(flutter_project, undo=True)
        assert rc == 0
        assert not (flutter_project / "shadow.sh").exists()
