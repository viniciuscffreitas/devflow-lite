"""Tests for devflow.init.planner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from devflow.init.detector import Stack
from devflow.init.planner import (
    PlanResult,
    generate_lock,
    render_artifacts,
)


@pytest.fixture
def flutter_root(tmp_path: Path) -> Path:
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    return tmp_path


class TestRenderArtifacts:
    def test_creates_all_required_artifacts_for_flutter(self, flutter_root: Path) -> None:
        result = render_artifacts(flutter_root, Stack.FLUTTER)
        assert isinstance(result, PlanResult)
        expected = {"Dockerfile.shadow", "shadow.sh", "sandbox.yaml", "sandbox.lock.yaml", "PROJECT_WIKI.md"}
        names = {p.name for p in result.created}
        assert expected.issubset(names)

    def test_does_not_clobber_existing_local_backup(self, flutter_root: Path, monkeypatch) -> None:
        (flutter_root / "Dockerfile.shadow").write_text("first\n", encoding="utf-8")
        (flutter_root / "Dockerfile.shadow.local").write_text("older backup\n", encoding="utf-8")
        monkeypatch.setenv("DEVFLOW_INIT_FORCE_BACKUP", "1")
        result = render_artifacts(flutter_root, Stack.FLUTTER)
        assert (flutter_root / "Dockerfile.shadow.local").read_text(encoding="utf-8") == "older backup\n"
        assert (flutter_root / "Dockerfile.shadow").read_text(encoding="utf-8") == "first\n"
        assert any(p.name == "Dockerfile.shadow" for p in result.preserved)

    def test_writes_manifest(self, flutter_root: Path) -> None:
        render_artifacts(flutter_root, Stack.FLUTTER)
        manifest_path = flutter_root / ".devflow" / "init-manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["stack"] == "flutter"
        assert {e["path"] for e in data["artifacts"]} >= {"Dockerfile.shadow", "shadow.sh", "sandbox.yaml"}

    def test_manifest_records_session_id(self, flutter_root: Path) -> None:
        render_artifacts(flutter_root, Stack.FLUTTER, session_id="sess-xyz")
        data = json.loads((flutter_root / ".devflow" / "init-manifest.json").read_text(encoding="utf-8"))
        assert data["session_id"] == "sess-xyz"

    def test_preserves_user_edited_shadow_sh_on_rerun(self, flutter_root: Path) -> None:
        render_artifacts(flutter_root, Stack.FLUTTER)
        shadow = flutter_root / "shadow.sh"
        shadow.write_text("#!/bin/bash\n# my hand edit\nflutter test --tags smoke\n", encoding="utf-8")

        second = render_artifacts(flutter_root, Stack.FLUTTER)
        assert "my hand edit" in shadow.read_text(encoding="utf-8")
        assert any(p.name == "shadow.sh" for p in second.preserved)

    def test_backs_up_pre_devflow_file_with_local_suffix(self, flutter_root: Path, monkeypatch) -> None:
        (flutter_root / "Dockerfile.shadow").write_text("# pre-existing user content\n", encoding="utf-8")
        monkeypatch.setenv("DEVFLOW_INIT_FORCE_BACKUP", "1")
        result = render_artifacts(flutter_root, Stack.FLUTTER)
        backup = flutter_root / "Dockerfile.shadow.local"
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == "# pre-existing user content\n"
        assert any(p.name == "Dockerfile.shadow" for p in result.backed_up)


class TestGenerateLock:
    def test_lock_contains_per_arch_digests_from_docker_manifest(self, tmp_path: Path) -> None:
        digest = "sha256:" + "a" * 64
        fake_manifest = json.dumps({
            "manifests": [
                {"digest": digest, "platform": {"architecture": "arm64"}},
                {"digest": digest, "platform": {"architecture": "amd64"}},
            ]
        })
        with patch("devflow.init.planner._docker_manifest_inspect", return_value=fake_manifest):
            out = generate_lock("ghcr.io/example:tag")
        assert "version: 1" in out
        assert "runner:" in out
        assert f"arm64: ghcr.io/example@{digest}" in out
        assert f"x86_64: ghcr.io/example@{digest}" in out

    def test_lock_emits_empty_runner_when_docker_unavailable(self, tmp_path: Path) -> None:
        with patch("devflow.init.planner._docker_manifest_inspect", return_value=None):
            out = generate_lock("ghcr.io/example:tag")
        assert "version: 1" in out
        assert "runner: {}" in out

    def test_lock_emits_empty_runner_when_image_ref_is_blank(self, tmp_path: Path) -> None:
        out = generate_lock("")
        assert "version: 1" in out
        assert "runner: {}" in out
