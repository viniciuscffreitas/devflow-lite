"""Wrap the ``devflow_sandbox heal`` CLI.

Init's retry layer only addresses composition failures (rc=70, missing
CLI); rc=1 means the project's own tests are broken and is surfaced
unchanged — heal's internal self-healing already handled whatever it
could at the test layer.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ShadowResult:
    rc: int
    log_path: Path
    duration_s: float
    verdict_payload: dict = field(default_factory=dict)


def run_shadow(
    root: Path,
    *,
    session_id: str,
    max_attempts: int = 3,
) -> ShadowResult:
    artifacts_dir = root / ".devflow" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir = root / ".devflow" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    log_path = root / ".devflow" / f"shadow-{session_id}.log"
    cmd = [
        "devflow_sandbox", "heal",
        "--config", str(root / "sandbox.yaml"),
        "--lock", str(root / "sandbox.lock.yaml"),
        "--source", str(root),
        "--wiki", str(wiki_dir),
        "--artifacts", str(artifacts_dir),
        "--max-attempts", str(max_attempts),
        "--auto-promote",
    ]

    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    except FileNotFoundError:
        log_path.write_text("[init] devflow_sandbox CLI not on PATH\n", encoding="utf-8")
        return ShadowResult(rc=2, log_path=log_path, duration_s=time.monotonic() - started)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log_path.write_text(f"[init] shadow run aborted: {exc}\n", encoding="utf-8")
        return ShadowResult(rc=2, log_path=log_path, duration_s=time.monotonic() - started)

    duration = time.monotonic() - started
    log_path.write_text(f"$ {' '.join(cmd)}\n\n{result.stdout}\n{result.stderr}", encoding="utf-8")

    verdict_payload: dict = {}
    verdict_path = artifacts_dir / "verdict.json"
    if verdict_path.exists():
        try:
            verdict_payload = json.loads(verdict_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            verdict_payload = {}

    return ShadowResult(rc=result.returncode, log_path=log_path, duration_s=duration, verdict_payload=verdict_payload)
