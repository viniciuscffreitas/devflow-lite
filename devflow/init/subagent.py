"""Composition-scoped fix proposer for devflow-init.

Separate from devflow_sandbox.claude_proposer.ClaudeSubprocessProposer:
that one fixes *test code* inside the container; this one fixes *shadow
composition* (shell script, Dockerfile, sandbox yaml). Different layer,
different prompt, different allowlist. Same ``claude -p`` transport.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from knowledge._types import Node

_ALLOWED_TARGETS: frozenset[str] = frozenset({
    "shadow.sh", "Dockerfile.shadow", "sandbox.yaml", "sandbox.lock.yaml",
})

_MIN_CONFIDENCE = 0.3

_PROMPT = """You are a devflow-init composition healer.

The ``devflow-init`` CLI rendered the artifacts below and ran them inside a
Docker shadow runner. Execution failed. Propose MINIMAL changes to the
artifacts (NOT to the user's application code) that would make the shadow
pass. You may only modify files in this allowlist: {allowed}.

## Attempt {attempt} of {max_attempts}

## Shadow log tail
```
{log_tail}
```

## Current shadow.sh
```
{shadow_sh}
```

## Current Dockerfile.shadow
```
{dockerfile}
```

## KB hits (tier-1 patterns that may apply)
{kb_hits_json}

## Required response format (JSON, no prose outside)
{{
    "unified_diff": "<apply with `patch -p0`>",
    "rationale": "<one short sentence>",
    "targets": ["shadow.sh"],
    "confidence": 0.0_to_1.0
}}
"""

_DIFF_TARGET_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


@dataclass
class FixProposal:
    unified_diff: str
    rationale: str
    targets: list[Path]
    confidence: float


class CompositionFixProposer:
    def __init__(self, *, claude_binary: str = "claude", timeout_s: int = 120) -> None:
        self._binary = claude_binary
        self._timeout = timeout_s

    def propose(
        self,
        *,
        root: Path,
        shadow_log: str,
        kb_hits: list[Node],
        attempt: int,
        max_attempts: int,
    ) -> FixProposal | None:
        prompt = _build_prompt(root=root, shadow_log=shadow_log, kb_hits=kb_hits,
                               attempt=attempt, max_attempts=max_attempts)
        try:
            result = subprocess.run(
                [self._binary, "-p", prompt],
                capture_output=True, text=True, timeout=self._timeout, check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

        if result.returncode != 0:
            return None
        return _parse_and_validate(result.stdout)


def _build_prompt(*, root: Path, shadow_log: str, kb_hits: list[Node], attempt: int, max_attempts: int) -> str:
    shadow_sh = _safe_read(root / "shadow.sh")
    dockerfile = _safe_read(root / "Dockerfile.shadow")
    tail = "\n".join(shadow_log.splitlines()[-200:])
    kb_payload = json.dumps([
        {"name": n.name, "summary": n.summary, "tier": n.tier, "source_repo": n.source_repo}
        for n in kb_hits
    ])
    return _PROMPT.format(
        allowed=sorted(_ALLOWED_TARGETS),
        attempt=attempt,
        max_attempts=max_attempts,
        log_tail=tail,
        shadow_sh=shadow_sh,
        dockerfile=dockerfile,
        kb_hits_json=kb_payload,
    )


def _parse_and_validate(stdout: str) -> FixProposal | None:
    stdout = stdout.strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(stdout[start:end + 1])
        except json.JSONDecodeError:
            return None

    for key in ("unified_diff", "rationale", "targets", "confidence"):
        if key not in payload:
            return None

    try:
        confidence = float(payload["confidence"])
    except (TypeError, ValueError):
        return None
    if confidence < _MIN_CONFIDENCE:
        return None

    declared = {str(t).strip() for t in payload["targets"]}
    if not declared or any(t not in _ALLOWED_TARGETS for t in declared):
        return None

    diff = str(payload["unified_diff"])
    diff_targets = set(_DIFF_TARGET_RE.findall(diff))
    if diff_targets and any(t not in _ALLOWED_TARGETS for t in diff_targets):
        return None

    return FixProposal(
        unified_diff=diff,
        rationale=str(payload["rationale"]).strip(),
        targets=[Path(t) for t in sorted(declared)],
        confidence=confidence,
    )


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "<missing>"
