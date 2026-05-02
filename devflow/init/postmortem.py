"""Post-mortem writer — called when RetryController exhausts the cap."""
from __future__ import annotations

import time
from pathlib import Path

from devflow.init.runner import ShadowResult


def write(
    *,
    session_id: str,
    stack: str,
    attempts: list[dict],
    final_result: ShadowResult,
    state_root: Path | None = None,
) -> Path:
    base = state_root or (Path.home() / ".claude" / "devflow" / "state")
    session_dir = base / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    target = session_dir / "init-post-mortem.md"
    target.write_text(_render(stack=stack, attempts=attempts, final=final_result), encoding="utf-8")
    return target


def _render(*, stack: str, attempts: list[dict], final: ShadowResult) -> str:
    ts = int(time.time())
    lines = [
        f"# devflow-init post-mortem — {ts}",
        "",
        f"- Stack: `{stack}`",
        f"- Final rc: `{final.rc}`",
        f"- Attempts: {len(attempts)}",
        f"- Log: `{final.log_path}`",
        "",
        "## Attempts",
        "",
    ]
    for a in attempts:
        lines.append(f"### Attempt {a.get('attempt', '?')} → rc={a.get('rc', '?')}")
        lines.append("")
        lines.append("```")
        lines.append(a.get("log_tail", "")[-2000:])
        lines.append("```")
        lines.append("")
        if a.get("diff_applied"):
            lines.append("Diff applied:")
            lines.append("```diff")
            lines.append(a["diff_applied"])
            lines.append("```")
            lines.append("")
    return "\n".join(lines) + "\n"
