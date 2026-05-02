"""Tests for cross_author_edit_guard.py.

Hook fires on PreToolUse Write|Edit|MultiEdit. Blocks the *first*
attempt to edit a file that another author has committed within
cross_author_window_days (default 7). Records the path in the per-session
ack file; the second attempt to edit the same path passes (assumes the
user pulled the changes / read the upstream after seeing the warning).

This is the smart-friction model: forces a pause + look at the recent
work, but never makes the user fight the hook to get work done.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


HOOKS_DIR = Path(__file__).parent
sys.path.insert(0, str(HOOKS_DIR))


@pytest.fixture
def guard(monkeypatch, tmp_path):
    monkeypatch.delenv("DEVFLOW_OVERRIDE_CROSS_AUTHOR", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "test-cross-author-session")
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(tmp_path / "state"))
    if "_stdin_cache" in sys.modules:
        from _stdin_cache import reset
        reset()
    if "cross_author_edit_guard" in sys.modules:
        importlib.reload(sys.modules["cross_author_edit_guard"])
    import cross_author_edit_guard
    # Always point ack base at our isolated tmp path. The hook appends
    # `<sid>/cross-author-ack/<key>.json` itself — don't duplicate the suffix.
    monkeypatch.setattr(
        cross_author_edit_guard, "_ACK_BASE",
        Path(tmp_path) / "ack-state",
    )
    return cross_author_edit_guard


@pytest.fixture
def repo():
    tmpdir = tempfile.mkdtemp(prefix="devflow-xauthor-")
    repo_path = Path(tmpdir)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "me@local"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Me"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_path, check=True)
    yield repo_path
    subprocess.run(["rm", "-rf", str(repo_path)], check=False)


def _commit_as(repo: Path, name: str, email: str, rel: str, content: str) -> None:
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    env = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo.parent),
    }
    subprocess.run(
        ["git", "commit", "-q", "-m", f"by {name}"],
        cwd=repo,
        env=env,
        check=True,
    )


def _commit_old(repo: Path, name: str, email: str, rel: str, content: str, days_ago: int) -> None:
    import time as _t
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    ts = int(_t.time()) - days_ago * 86400
    date = f"{ts} +0000"
    env = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": date,
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo.parent),
    }
    subprocess.run(
        ["git", "commit", "-q", "-m", f"old {name}"],
        cwd=repo,
        env=env,
        check=True,
    )


def _payload(file_path: str, repo: Path, tool: str = "Edit") -> str:
    return json.dumps(
        {"tool_name": tool, "tool_input": {"file_path": file_path}, "cwd": str(repo)}
    )


def _run(guard_module, payload: str, monkeypatch) -> int:
    monkeypatch.setattr("sys.stdin", _StringIO(payload))
    if "_stdin_cache" in sys.modules:
        from _stdin_cache import reset
        reset()
    try:
        return guard_module.main()
    except SystemExit as e:
        return int(e.code or 0)


class _StringIO:
    def __init__(self, s: str):
        self._s = s
        self._pos = 0

    def read(self, *a, **kw):
        rest = self._s[self._pos:]
        self._pos = len(self._s)
        return rest


def test_blocks_when_other_author_recent(guard, repo, monkeypatch, capsys):
    _commit_as(repo, "Maria", "maria@team", "vendor.py", "x = 1\n")
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 2
    err = capsys.readouterr().err
    assert "Maria" in err
    assert "vendor.py" in err
    assert "retry the same edit" in err.lower() or "retry" in err.lower()


def test_passes_self_author(guard, repo, monkeypatch):
    _commit_as(repo, "Me", "me@local", "vendor.py", "x = 1\n")
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 0


def test_passes_outside_window(guard, repo, monkeypatch):
    _commit_old(repo, "Maria", "maria@team", "vendor.py", "x = 1\n", days_ago=30)
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 0


def test_second_attempt_passes_after_ack(guard, repo, monkeypatch):
    _commit_as(repo, "Maria", "maria@team", "vendor.py", "x = 1\n")
    file_path = str(repo / "vendor.py")
    rc1 = _run(guard, _payload(file_path, repo), monkeypatch)
    assert rc1 == 2
    rc2 = _run(guard, _payload(file_path, repo), monkeypatch)
    assert rc2 == 0


def test_env_override(guard, repo, monkeypatch):
    _commit_as(repo, "Maria", "maria@team", "vendor.py", "x = 1\n")
    monkeypatch.setenv("DEVFLOW_OVERRIDE_CROSS_AUTHOR", "1")
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 0


def test_outside_repo_passes(guard, monkeypatch, tmp_path):
    rc = _run(guard, _payload(str(tmp_path / "x.py"), tmp_path), monkeypatch)
    assert rc == 0


def test_non_edit_tool_passes(guard, repo, monkeypatch):
    _commit_as(repo, "Maria", "maria@team", "vendor.py", "x = 1\n")
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo, tool="Read"), monkeypatch)
    assert rc == 0


def test_disabled_via_config(guard, repo, monkeypatch):
    (repo / ".devflow-config.json").write_text(
        json.dumps({"disabled_hooks": ["cross_author_edit_guard"]})
    )
    _commit_as(repo, "Maria", "maria@team", "vendor.py", "x = 1\n")
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 0


def test_window_configurable_per_project(guard, repo, monkeypatch):
    # Set window to 1 day, file modified 5 days ago by other → should pass
    (repo / ".devflow-config.json").write_text(
        json.dumps({"cross_author_window_days": 1})
    )
    _commit_old(repo, "Maria", "maria@team", "vendor.py", "x = 1\n", days_ago=5)
    rc = _run(guard, _payload(str(repo / "vendor.py"), repo), monkeypatch)
    assert rc == 0


def test_unborn_branch_passes(guard, monkeypatch, tmp_path):
    """Repo with no commits yet — nothing to compare against."""
    fresh = Path(tempfile.mkdtemp(prefix="devflow-xauthor-fresh-"))
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=fresh, check=True)
    subprocess.run(["git", "config", "user.email", "me@local"], cwd=fresh, check=True)
    subprocess.run(["git", "config", "user.name", "Me"], cwd=fresh, check=True)
    rc = _run(guard, _payload(str(fresh / "new.py"), fresh), monkeypatch)
    assert rc == 0
    subprocess.run(["rm", "-rf", str(fresh)], check=False)
