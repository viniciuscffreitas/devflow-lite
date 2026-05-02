"""Init manifest for rollback via ``devflow-init --undo``."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

_MANIFEST_PATH = Path(".devflow") / "init-manifest.json"


@dataclass
class ArtifactEntry:
    path: str
    sha256: str


@dataclass
class InitManifest:
    created_at: int
    stack: str
    session_id: str
    artifacts: list[ArtifactEntry]
    git_hook_backup: str | None

    def save(self, root: Path) -> Path:
        target = root / _MANIFEST_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, root: Path) -> "InitManifest":
        raw = json.loads((root / _MANIFEST_PATH).read_text(encoding="utf-8"))
        return cls(
            created_at=int(raw["created_at"]),
            stack=str(raw["stack"]),
            session_id=str(raw["session_id"]),
            artifacts=[ArtifactEntry(**a) for a in raw.get("artifacts", [])],
            git_hook_backup=raw.get("git_hook_backup"),
        )


def undo(root: Path) -> int:
    manifest_path = root / _MANIFEST_PATH
    if not manifest_path.exists():
        return 1
    m = InitManifest.load(root)
    drift = False
    for entry in m.artifacts:
        target = root / entry.path
        if not target.exists():
            continue
        if _sha256(target) != entry.sha256:
            drift = True
            continue
        target.unlink()
    if m.git_hook_backup:
        backup = root / m.git_hook_backup
        if backup.exists():
            # "pre-push.local" -> "pre-push" (drop trailing .local)
            real = backup.parent / backup.stem
            shutil.move(str(backup), str(real))
    manifest_path.unlink()
    return 2 if drift else 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
