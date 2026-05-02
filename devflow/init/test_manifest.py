"""Tests for devflow.init.manifest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from devflow.init.manifest import ArtifactEntry, InitManifest, undo


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def initialized_root(tmp_path: Path) -> Path:
    for name, content in [
        ("Dockerfile.shadow", "FROM scratch\n"),
        ("shadow.sh", "#!/bin/bash\necho hi\n"),
        ("sandbox.yaml", "runner: {}\n"),
    ]:
        (tmp_path / name).write_text(content, encoding="utf-8")
    manifest = InitManifest(
        created_at=100,
        stack="flutter",
        session_id="s1",
        artifacts=[
            ArtifactEntry(path="Dockerfile.shadow", sha256=_sha("FROM scratch\n")),
            ArtifactEntry(path="shadow.sh", sha256=_sha("#!/bin/bash\necho hi\n")),
            ArtifactEntry(path="sandbox.yaml", sha256=_sha("runner: {}\n")),
        ],
        git_hook_backup=None,
    )
    manifest.save(tmp_path)
    return tmp_path


class TestInitManifest:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        m = InitManifest(created_at=1, stack="flutter", session_id="s",
                         artifacts=[ArtifactEntry(path="a.sh", sha256="abc")],
                         git_hook_backup=None)
        m.save(tmp_path)
        loaded = InitManifest.load(tmp_path)
        assert loaded.stack == "flutter"
        assert loaded.session_id == "s"
        assert loaded.artifacts[0].path == "a.sh"


class TestUndo:
    def test_removes_tracked_files(self, initialized_root: Path) -> None:
        rc = undo(initialized_root)
        assert rc == 0
        assert not (initialized_root / "Dockerfile.shadow").exists()
        assert not (initialized_root / "shadow.sh").exists()
        assert not (initialized_root / "sandbox.yaml").exists()
        assert not (initialized_root / ".devflow" / "init-manifest.json").exists()

    def test_preserves_drifted_files_and_warns(self, initialized_root: Path) -> None:
        (initialized_root / "shadow.sh").write_text("# user edit\n", encoding="utf-8")
        rc = undo(initialized_root)
        assert rc == 2
        assert (initialized_root / "shadow.sh").exists()
        assert not (initialized_root / "Dockerfile.shadow").exists()

    def test_missing_manifest_returns_1(self, tmp_path: Path) -> None:
        assert undo(tmp_path) == 1

    def test_restores_pre_push_local_backup(self, initialized_root: Path) -> None:
        git_hooks = initialized_root / ".git" / "hooks"
        git_hooks.mkdir(parents=True)
        (git_hooks / "pre-push").write_text("# devflow\n", encoding="utf-8")
        (git_hooks / "pre-push.local").write_text("# user old\n", encoding="utf-8")

        manifest_path = initialized_root / ".devflow" / "init-manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["git_hook_backup"] = ".git/hooks/pre-push.local"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        undo(initialized_root)
        assert (git_hooks / "pre-push").read_text(encoding="utf-8") == "# user old\n"
        assert not (git_hooks / "pre-push.local").exists()
