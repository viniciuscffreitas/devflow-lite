"""Tests for devflow.init.runner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


from devflow.init.runner import run_shadow


def _make_verdict(result: str = "pass", exit_code: int = 0) -> dict:
    return {"result": result, "exit_code": exit_code, "snapshot_hash": "abc", "attempts": 1}


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    import subprocess
    return subprocess.CompletedProcess(
        args=["devflow_sandbox", "heal"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestRunShadow:
    def test_invokes_heal_with_expected_args(self, tmp_path: Path) -> None:
        artifacts = tmp_path / ".devflow" / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "verdict.json").write_text(json.dumps(_make_verdict()), encoding="utf-8")

        with patch("devflow.init.runner.subprocess.run", return_value=_completed(0)) as m:
            result = run_shadow(tmp_path, session_id="sess1", max_attempts=3)

        called = m.call_args[0][0]
        assert called[0:2] == ["devflow_sandbox", "heal"]
        assert "--config" in called and str(tmp_path / "sandbox.yaml") in called
        assert "--lock" in called and str(tmp_path / "sandbox.lock.yaml") in called
        assert "--max-attempts" in called and "3" in called
        assert "--auto-promote" in called
        assert result.rc == 0
        assert result.verdict_payload["result"] == "pass"

    def test_rc_propagates_test_failure(self, tmp_path: Path) -> None:
        artifacts = tmp_path / ".devflow" / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "verdict.json").write_text(json.dumps(_make_verdict(result="fail", exit_code=1)), encoding="utf-8")

        with patch("devflow.init.runner.subprocess.run", return_value=_completed(1)):
            result = run_shadow(tmp_path, session_id="sess1")

        assert result.rc == 1

    def test_sandbox_error_returns_70(self, tmp_path: Path) -> None:
        with patch("devflow.init.runner.subprocess.run", return_value=_completed(70, stderr="[sandbox error] lock missing")):
            result = run_shadow(tmp_path, session_id="sess1")
        assert result.rc == 70
        assert result.verdict_payload == {}

    def test_cli_missing_returns_2(self, tmp_path: Path) -> None:
        with patch("devflow.init.runner.subprocess.run", side_effect=FileNotFoundError()):
            result = run_shadow(tmp_path, session_id="sess1")
        assert result.rc == 2
        assert "devflow_sandbox CLI not on PATH" in result.log_path.read_text(encoding="utf-8")

    def test_writes_log_file(self, tmp_path: Path) -> None:
        with patch("devflow.init.runner.subprocess.run", return_value=_completed(0, stdout="OK\n")):
            result = run_shadow(tmp_path, session_id="sess1")
        assert result.log_path.exists()
        assert "OK" in result.log_path.read_text(encoding="utf-8")
