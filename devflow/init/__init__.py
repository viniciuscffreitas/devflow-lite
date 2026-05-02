"""devflow.init — agentic bootstrap for DevFlow-enabled projects."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from knowledge.provider import KnowledgeProvider

from devflow.init.detector import detect_stack
from devflow.init.kb_query import ensure_kb_seeded, query_patterns_for_stack
from devflow.init.manifest import undo as manifest_undo
from devflow.init.planner import render_artifacts
from devflow.init.postmortem import write as write_postmortem
from devflow.init.retry import RetryController
from devflow.init.subagent import CompositionFixProposer

__all__ = ["run_init"]


def run_init(
    path: Path | str = ".",
    *,
    retries: int = 3,
    kb_seed_threshold: int = 8,
    session_id: str | None = None,
    undo: bool = False,
) -> int:
    root = Path(path).resolve()
    sid = session_id or os.environ.get("CLAUDE_SESSION_ID", "default")

    if undo:
        return manifest_undo(root)

    stack = detect_stack(root)
    print(f"[devflow init] detected stack: {stack.value}")

    if not ensure_kb_seeded(threshold=kb_seed_threshold):
        print("[devflow init] KB not seeded to threshold — proceeding with empty patterns")

    with KnowledgeProvider.open(force_enabled=True) as kp:
        patterns = query_patterns_for_stack(kp, stack)
        print(f"[devflow init] {len(patterns)} KB patterns retrieved")

    plan = render_artifacts(root, stack, session_id=sid)
    for p in plan.created:
        print(f"[devflow init] created: {p.relative_to(root)}")
    for p in plan.preserved:
        print(f"[devflow init] preserved: {p.relative_to(root)}")
    for p in plan.backed_up:
        print(f"[devflow init] backed up: {p.relative_to(root)}.local")

    proposer = CompositionFixProposer()
    controller = RetryController(cap=retries)
    result, attempts = controller.run(root, proposer=proposer, session_id=sid, kb_hits=patterns)

    if result.rc == 0:
        print(f"[devflow init] GREEN — shadow passed. Log: {result.log_path}")
        return 0

    state_root_env = os.environ.get("DEVFLOW_STATE_DIR")
    state_root = Path(state_root_env) if state_root_env else None
    write_postmortem(
        session_id=sid,
        stack=stack.value,
        attempts=attempts,
        final_result=result,
        state_root=state_root,
    )
    print(f"[devflow init] EXHAUSTED — rc={result.rc}. See post-mortem.", file=sys.stderr)
    return 1
