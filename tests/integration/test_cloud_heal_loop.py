# tests/integration/test_cloud_heal_loop.py
"""End-to-end smoke test for the Mac → VPS → Heal → Commit → Push loop.

Stubs the cloud (`evaluate_remote`) and the network push (`_do_push`), but
exercises every other component for real: shadow_runner argparse, cloud
verdict ingest, patch apply, journey markdown, auto_promote git ops.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from hooks.shadow_runner import run_shadow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_cloud_heal_full_loop(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "checkout", "-b", "feat/x")
    _git(project, "config", "user.email", "x@x.io")
    _git(project, "config", "user.name", "x")
    (project / "sandbox.yaml").write_text("runner: {image_ref: r}\n")
    (project / "sandbox.lock.yaml").write_text("images: {}\n")
    (project / "src.py").write_text("v1\n")
    _git(project, "add", ".")
    _git(project, "commit", "-qm", "init")

    verdict = {
        "result": "pass", "healed": True, "heal_attempts": 1,
        "pre_heal_run_stderr_tail": "AssertionError: 1 != 2",
        "healing_patches": [{"files": [
            {"path": "src.py", "content_b64": "djIK"},  # base64 of "v2\n"
        ]}],
        "patch": "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-v1\n+v2\n",
    }

    monkeypatch.setenv("DEVFLOW_CLOUD_ENDPOINT", "http://stub")
    monkeypatch.setenv("DEVFLOW_CLOUD_API_KEY", "x")
    monkeypatch.setenv("DEVFLOW_CLOUD_CLIENT_ID", "x")

    with patch("hooks.shadow_runner.evaluate_remote", return_value=verdict), \
         patch("hooks._auto_promote._do_push", return_value=(0, "")) as do_push, \
         patch("hooks._pr_comment._gh_path", return_value=None):
        passed, summary = run_shadow(project, "sess", heal=True, no_push=False)

    assert passed is True
    assert summary == ""
    # File got rewritten by the heal patch
    assert (project / "src.py").read_text() == "v2\n"
    # Commit landed locally
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=project, capture_output=True, text=True, check=True,
    ).stdout
    assert "autonomous heal for src.py" in log
    # Push got called
    do_push.assert_called_once()
