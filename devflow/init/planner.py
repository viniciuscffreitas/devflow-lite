"""Artifact renderer for devflow-init.

Honors ``_write_once`` semantics: never overwrites an existing file. On
``DEVFLOW_INIT_FORCE_BACKUP=1`` (used by --force), an existing file is
moved to ``<name>.local`` before the new version is written. ``.local``
matches the suffix used by the pre-push hook for consistency.

The ``sandbox.lock.yaml`` body is hand-rolled YAML (no PyYAML dep) since
devflow's base package does not declare PyYAML.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

from devflow.init.detector import Stack
from devflow.init.manifest import ArtifactEntry, InitManifest

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "scripts" / "templates"

_TEMPLATE_MAP: dict[Stack, dict[str, str]] = {
    Stack.FLUTTER: {
        "Dockerfile.shadow": "Dockerfile.shadow.flutter.tmpl",
        "shadow.sh": "shadow.sh.flutter.tmpl",
    },
    Stack.PYTHON: {"Dockerfile.shadow": "Dockerfile.shadow.python.tmpl"},
    Stack.NODE: {"Dockerfile.shadow": "Dockerfile.shadow.node.tmpl"},
    Stack.RUST: {"Dockerfile.shadow": "Dockerfile.shadow.generic.tmpl"},
    Stack.GO: {"Dockerfile.shadow": "Dockerfile.shadow.generic.tmpl"},
    Stack.GENERIC: {"Dockerfile.shadow": "Dockerfile.shadow.generic.tmpl"},
}

_DEFAULT_FLUTTER_IMAGE = "ghcr.io/viniciuscffreitas/devflow-shadow-runner:flutter-stable"


def _flutter_image_ref() -> str:
    # Env override lets local dev point at a private/localhost registry before the
    # canonical tag ships to ghcr. Keeps the production default unchanged.
    return os.environ.get("DEVFLOW_FLUTTER_BASE_IMAGE", _DEFAULT_FLUTTER_IMAGE)

_TEST_CMDS: dict[Stack, list[str]] = {
    Stack.FLUTTER: ["bash", "/app/shadow.sh"],
    Stack.PYTHON: ["pytest", "-q"],
    Stack.NODE: ["npm", "test", "--silent"],
    Stack.RUST: ["cargo", "test", "--quiet"],
    Stack.GO: ["go", "test", "./..."],
    Stack.GENERIC: ["echo", "configure TEST_CMD in sandbox.yaml"],
}

_DOCKER_ARCH_TO_SANDBOX: dict[str, str] = {
    "arm64": "arm64",
    "amd64": "x86_64",
}


class PlanResult(NamedTuple):
    created: list[Path]
    preserved: list[Path]
    backed_up: list[Path]


def render_artifacts(
    root: Path,
    stack: Stack,
    *,
    session_id: str = "default",
) -> PlanResult:
    result = PlanResult(created=[], preserved=[], backed_up=[])
    force_backup = os.environ.get("DEVFLOW_INIT_FORCE_BACKUP") == "1"

    template_map = _TEMPLATE_MAP.get(stack, _TEMPLATE_MAP[Stack.GENERIC])
    flutter_image = _flutter_image_ref()
    for target_name, tmpl_name in template_map.items():
        tmpl_text = (_TEMPLATES_DIR / tmpl_name).read_text(encoding="utf-8")
        if stack is Stack.FLUTTER:
            tmpl_text = tmpl_text.replace("{{FLUTTER_BASE_IMAGE}}", flutter_image)
        _render_literal(root / target_name, tmpl_text, result, force_backup=force_backup)

    sandbox_text = _render_sandbox_yaml(stack)
    _render_literal(root / "sandbox.yaml", sandbox_text, result, force_backup=force_backup)

    image_ref = _flutter_image_ref() if stack is Stack.FLUTTER else ""
    lock_text = generate_lock(image_ref)
    _render_literal(root / "sandbox.lock.yaml", lock_text, result, force_backup=force_backup)

    wiki_text = _render_wiki(stack)
    _render_literal(root / "PROJECT_WIKI.md", wiki_text, result, force_backup=force_backup)

    _write_manifest(root, stack, result, session_id=session_id)
    return result


def generate_lock(image_ref: str) -> str:
    header = (_TEMPLATES_DIR / "sandbox.lock.yaml.tmpl").read_text(encoding="utf-8")
    images: dict[str, dict[str, str]] = {"runner": {}}
    raw = _docker_manifest_inspect(image_ref) if image_ref else None
    if raw:
        repo = _strip_tag(image_ref)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        for entry in payload.get("manifests", []):
            digest = entry.get("digest")
            docker_arch = entry.get("platform", {}).get("architecture")
            sandbox_arch = _DOCKER_ARCH_TO_SANDBOX.get(docker_arch)
            if digest and sandbox_arch:
                images["runner"][sandbox_arch] = f"{repo}@{digest}"
    body = _emit_lock_yaml(images)
    return f"{header}\n{body}"


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _docker_manifest_inspect(image_ref: str) -> str | None:
    cmd = ["docker", "manifest", "inspect", image_ref]
    # Local dev registries (e.g. registry:2 on localhost) speak plain HTTP and need
    # --insecure; remote registries reject the flag, so only add it when we can tell.
    if any(image_ref.startswith(h) for h in _LOCAL_HOSTS):
        cmd.insert(3, "--insecure")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


def _strip_tag(image_ref: str) -> str:
    last_slash = image_ref.rsplit("/", 1)[-1]
    if ":" in last_slash:
        return image_ref.rpartition(":")[0]
    return image_ref


def _emit_lock_yaml(images: dict[str, dict[str, str]]) -> str:
    lines = ["version: 1", "images:"]
    for key, arch_map in images.items():
        if not arch_map:
            lines.append(f"  {key}: {{}}")
        else:
            lines.append(f"  {key}:")
            for arch_name, ref in arch_map.items():
                lines.append(f"    {arch_name}: {ref}")
    return "\n".join(lines) + "\n"


def _render_sandbox_yaml(stack: Stack) -> str:
    cmd = _TEST_CMDS[stack]
    command_yaml_list = "\n" + "\n".join(f"    - {token}" for token in cmd)
    body = (_TEMPLATES_DIR / "sandbox.yaml.tmpl").read_text(encoding="utf-8").replace(
        "{{TEST_CMD}}", command_yaml_list
    )
    # Flutter/Dart tooling writes .dart_tool/ and build/ at `flutter pub get`
    # time. A readonly mount would trip that before any test runs.
    # `flutter pub get` also needs pub.dev egress on the first cold run — the
    # base image pre-caches the Flutter SDK itself but cannot know the target
    # project's transitive pub deps. Bridge mode is the pragmatic baseline;
    # a future hermetic pub cache can flip this back to internal.
    if stack is Stack.FLUTTER:
        body = body.replace("readonly: true", "readonly: false")
        body = body.replace("network_mode: internal", "network_mode: bridge")
    return body


def _render_wiki(stack: Stack) -> str:
    cmd_human = " ".join(_TEST_CMDS[stack])
    return (
        (_TEMPLATES_DIR / "PROJECT_WIKI.md.tmpl").read_text(encoding="utf-8")
        .replace("{{STACK_HUMAN}}", stack.value.capitalize())
        .replace("{{TEST_CMD_HUMAN}}", cmd_human)
    )


def _render_literal(target: Path, content: str, result: PlanResult, *, force_backup: bool) -> None:
    if target.exists():
        if force_backup:
            backup = target.with_name(target.name + ".local")
            if backup.exists():
                # Refuse to clobber a prior .local backup — the user may still need it.
                # Treat the current file as preserved so the caller sees a no-op, not a rewrite.
                result.preserved.append(target)
                return
            shutil.move(str(target), str(backup))
            result.backed_up.append(target)
        else:
            result.preserved.append(target)
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    result.created.append(target)


def _write_manifest(root: Path, stack: Stack, plan: PlanResult, *, session_id: str) -> None:
    # .devflow/ entries would describe the manifest itself — exclude them so
    # --undo has a clean list of files to remove.
    devflow_dir = root / ".devflow"
    artifacts = [
        ArtifactEntry(path=str(p.relative_to(root)), sha256=_sha256(p))
        for p in plan.created
        if p.is_file() and not p.is_relative_to(devflow_dir)
    ]
    InitManifest(
        created_at=int(time.time()),
        stack=stack.value,
        session_id=session_id,
        artifacts=artifacts,
        git_hook_backup=None,
    ).save(root)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
