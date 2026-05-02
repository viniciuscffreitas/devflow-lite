"""codeowners_check.py — PostToolUse Write|Edit hook.

When the edited file matches a CODEOWNERS rule whose owner is not the
current git user, prints a non-blocking advisory naming the reviewer
to ping in the PR. Always exits 0.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    get_state_dir,
    is_hook_disabled,
    load_devflow_config,
    read_hook_stdin,
)


def _already_pinged(state_dir: Path, rel: str) -> bool:
    """Per-session dedup: True iff rel already pinged once for this session.

    Avoids re-warning the same file 5x in a row when an Edit/MultiEdit
    pass touches it repeatedly. Reset on next session — the dev does
    want a fresh ping if they come back the next day.
    """
    log = state_dir / "codeowners-pinged.txt"
    if not log.exists():
        return False
    try:
        return rel in {line.strip() for line in log.read_text().splitlines()}
    except OSError:
        return False


def _mark_pinged(state_dir: Path, rel: str) -> None:
    log = state_dir / "codeowners-pinged.txt"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(rel + "\n")
    except OSError:
        pass


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(cwd),
            check=False,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _find_codeowners(repo: Path) -> Path | None:
    for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        p = repo / rel
        if p.exists():
            return p
    return None


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    p = pattern.strip()
    if p.startswith("/"):
        p = p[1:]
        anchor = r"^"
    else:
        anchor = r"(?:^|/)"
    dir_only = p.endswith("/")
    if dir_only:
        p = p[:-1]
    p = (
        re.escape(p)
        .replace(r"\*\*", ".*")
        .replace(r"\*", "[^/]*")
        .replace(r"\?", "[^/]")
    )
    tail = r"(?:/.*)?$"
    return re.compile(anchor + p + tail)


def _parse_codeowners(path: Path) -> list[tuple[re.Pattern[str], list[str]]]:
    rules: list[tuple[re.Pattern[str], list[str]]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, owners = parts[0], parts[1:]
        rules.append((_glob_to_regex(pattern), owners))
    return rules


def main() -> int:
    if is_hook_disabled("codeowners_check"):
        return 0

    payload = read_hook_stdin()
    file_path = (payload.get("tool_input", {}) or {}).get("file_path", "")
    if not file_path:
        return 0

    fp = Path(file_path)
    repo = fp.parent
    while repo != repo.parent and not (repo / ".git").exists():
        repo = repo.parent
    if not (repo / ".git").exists():
        return 0

    co = _find_codeowners(repo)
    if not co:
        return 0

    try:
        rel = str(fp.relative_to(repo))
    except ValueError:
        return 0

    rules = _parse_codeowners(co)
    matched: list[str] = []
    for pat, owners in rules:
        if pat.match(rel):
            matched = owners

    if not matched:
        return 0

    me = _git("config", "user.email", cwd=repo)
    me_name = "@" + (me.split("@")[0] if me else "")
    if any(o == me_name or o.lower() == me_name.lower() for o in matched):
        return 0

    cfg = load_devflow_config(repo)
    if cfg.get("codeowners_dedup_per_session", True):
        try:
            state_dir = get_state_dir()
            if _already_pinged(state_dir, rel):
                return 0
            _mark_pinged(state_dir, rel)
        except Exception:
            pass

    print(f"[devflow:codeowners] {rel} owned by {' '.join(matched)} — ping in PR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
