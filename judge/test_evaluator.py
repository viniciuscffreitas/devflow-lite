"""Evaluator shape tests — colocated so the TDD mirror sees them.

Full behavioral coverage lives in hooks/tests/test_judge.py and
hooks/tests/test_judge_oversight_semantic.py. This file pins the new
Oversight-Semântico fields on JudgeResult so a rename or removal is caught
by a dedicated test next to the source.
"""
from __future__ import annotations

from dataclasses import fields


class TestJudgeResultSemanticFields:
    def test_oversight_semantic_fields_present(self):
        from judge.evaluator import JudgeResult
        names = {f.name for f in fields(JudgeResult)}
        for name in (
            "accidental_complexity_status",
            "accidental_complexity_evidence",
            "design_system_adherence_status",
            "design_system_adherence_evidence",
            "agentic_legibility_score",
            "agentic_legibility_evidence",
        ):
            assert name in names, f"JudgeResult missing {name}"

    def test_semantic_field_defaults_are_safe(self):
        from judge.evaluator import JudgeResult
        r = JudgeResult(
            task_id="t",
            verdict="pass",
            lob_violation=False, lob_evidence=None,
            duplication=False, duplication_evidence=None,
            type_contract_violation=False, type_contract_evidence=None,
            unjustified_complexity=False, complexity_evidence=None,
            naming_consistency_score=1.0, naming_evidence=None,
            edge_case_coverage="adequate",
            spec_fulfilled="yes", spec_evidence=None,
        )
        assert r.accidental_complexity_status == "ok"
        assert r.design_system_adherence_status == "na"
        assert r.agentic_legibility_score == 1.0


class TestBuildReflectionSummaryApi:
    def test_build_reflection_summary_is_staticmethod(self):
        from judge.evaluator import HarnessJudge
        assert callable(getattr(HarnessJudge, "build_reflection_summary", None))


class TestCloudJudgeFallback:
    """Cover the CI fallback path: GitHub Actions runners cannot ship the
    authenticated `claude` CLI, so the judge must transparently route through
    the VPS `/v1/judge` endpoint instead of FileNotFoundError-ing."""

    def test_should_use_cloud_judge_skips_outside_ci(self, monkeypatch):
        from judge.evaluator import _should_use_cloud_judge

        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("DEVFLOW_FORCE_CLOUD_JUDGE", raising=False)
        assert _should_use_cloud_judge() is False

    def test_should_use_cloud_judge_fires_when_ci_and_no_binary(
        self, monkeypatch, tmp_path
    ):
        from judge import evaluator

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        # Empty PATH so shutil.which("claude") returns None.
        monkeypatch.setenv("PATH", str(tmp_path))
        assert evaluator._should_use_cloud_judge() is True

    def test_should_use_cloud_judge_skips_when_binary_present(
        self, monkeypatch, tmp_path
    ):
        from judge import evaluator
        import stat

        fake = tmp_path / "claude"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("PATH", str(tmp_path))
        assert evaluator._should_use_cloud_judge() is False

    def test_run_cloud_subprocess_returns_none_without_config(self, monkeypatch):
        from judge.evaluator import HarnessJudge

        for var in (
            "DEVFLOW_CLOUD_ENDPOINT",
            "DEVFLOW_CLOUD_API_KEY",
            "DEVFLOW_CLOUD_CLIENT_ID",
            "DEVFLOW_CLOUD_CREDENTIALS",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DEVFLOW_CLOUD_CREDENTIALS", "/nonexistent/cred.json")

        assert HarnessJudge()._run_cloud_subprocess("p") is None

    def test_run_cloud_subprocess_wraps_remote_envelope(self, monkeypatch):
        from judge.evaluator import HarnessJudge, _RemoteCompleted
        import _cloud_client as cc

        monkeypatch.setenv("DEVFLOW_CLOUD_ENDPOINT", "https://x/v1/evaluate")
        monkeypatch.setenv("DEVFLOW_CLOUD_API_KEY", "k")
        monkeypatch.setenv("DEVFLOW_CLOUD_CLIENT_ID", "c")
        monkeypatch.delenv("DEVFLOW_CLOUD_CREDENTIALS", raising=False)

        captured: dict = {}

        def fake_judge_remote(**kwargs):
            captured.update(kwargs)
            return {
                "returncode": 0,
                "stdout": '{"type":"result","result":"{}"}',
                "stderr": "",
            }

        monkeypatch.setattr(cc, "judge_remote", fake_judge_remote)

        result = HarnessJudge()._run_cloud_subprocess("the-prompt")
        assert isinstance(result, _RemoteCompleted)
        assert result.returncode == 0
        assert "result" in result.stdout
        assert captured["prompt"] == "the-prompt"
        assert captured["model"] == "claude-haiku-4-5-20251001"
        assert captured["setting_sources"] == ""

    def test_run_cloud_subprocess_swallows_transport_errors(self, monkeypatch):
        from judge.evaluator import HarnessJudge, _RemoteCompleted
        import _cloud_client as cc

        monkeypatch.setenv("DEVFLOW_CLOUD_ENDPOINT", "https://x/v1/evaluate")
        monkeypatch.setenv("DEVFLOW_CLOUD_API_KEY", "k")
        monkeypatch.setenv("DEVFLOW_CLOUD_CLIENT_ID", "c")
        monkeypatch.delenv("DEVFLOW_CLOUD_CREDENTIALS", raising=False)

        def boom(**kwargs):
            raise RuntimeError("503 unavailable")

        monkeypatch.setattr(cc, "judge_remote", boom)

        result = HarnessJudge()._run_cloud_subprocess("p")
        assert isinstance(result, _RemoteCompleted)
        assert result.returncode != 0
        assert "503 unavailable" in result.stderr
