"""Tests for test_deletion_guard.py.

Hook fires on PreToolUse Bash matching `git commit`. Blocks when staged
diff deletes a test file. Override via Override-Test-Deletion trailer in
the commit message or DEVFLOW_OVERRIDE_TEST_DELETION env var.

Test patterns recognised across ecosystems:
  - Python:  test_*.py, *_test.py
  - JS/TS:   *.test.ts, *.test.tsx, *.test.js, *.spec.ts, *.spec.js
  - Go:      *_test.go
  - Dart:    *_test.dart, test/*.dart
  - Ruby:    *_spec.rb, *_test.rb
  - Rust:    tests/*.rs (path-based)
  - Kotlin:  *Test.kt, *Spec.kt
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
    monkeypatch.delenv("DEVFLOW_OVERRIDE_TEST_DELETION", raising=False)
    if "_stdin_cache" in sys.modules:
        from _stdin_cache import reset
        reset()
    if "test_deletion_guard" in sys.modules:
        importlib.reload(sys.modules["test_deletion_guard"])
    import test_deletion_guard
    return test_deletion_guard


@pytest.fixture
def repo():
    """Real git repo. Use mkdtemp (not pytest tmp_path) — pytest's
    test-named dirs trip path-based test detection inside the hook."""
    tmpdir = tempfile.mkdtemp(prefix="devflow-deletion-")
    repo_path = Path(tmpdir)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "dev@local"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Local Dev"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_path, check=True)
    yield repo_path
    subprocess.run(["rm", "-rf", str(repo_path)], check=False)


def _stage_delete(repo: Path, rel: str) -> None:
    """Stage deletion of an existing committed file."""
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("def test_x():\n    assert True\n")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add test"], cwd=repo, check=True)
    subprocess.run(["git", "rm", "-q", rel], cwd=repo, check=True)


def _stage_add(repo: Path, rel: str, content: str = "x = 1\n") -> None:
    full = repo / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


def _payload(cmd: str, cwd: Path) -> str:
    return json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
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


def test_non_commit_command_passes(guard, repo, monkeypatch, capsys):
    _stage_delete(repo, "tests/test_foo.py")
    rc = _run(guard, _payload("git status", repo), monkeypatch)
    assert rc == 0
    assert "BLOCK" not in capsys.readouterr().err


def test_blocks_python_test_deletion(guard, repo, monkeypatch, capsys):
    _stage_delete(repo, "tests/test_vendor.py")
    rc = _run(guard, _payload("git commit -m 'cleanup'", repo), monkeypatch)
    assert rc == 2
    err = capsys.readouterr().err
    assert "test_vendor.py" in err
    assert "Override-Test-Deletion" in err


def test_blocks_dart_test_deletion(guard, repo, monkeypatch, capsys):
    _stage_delete(repo, "test/widget_test.dart")
    rc = _run(guard, _payload("git commit -m 'remove'", repo), monkeypatch)
    assert rc == 2
    assert "widget_test.dart" in capsys.readouterr().err


def test_blocks_ts_spec_deletion(guard, repo, monkeypatch, capsys):
    _stage_delete(repo, "src/checkout.spec.ts")
    rc = _run(guard, _payload("git commit -m 'wip'", repo), monkeypatch)
    assert rc == 2
    assert "checkout.spec.ts" in capsys.readouterr().err


def test_passes_when_only_source_files_modified(guard, repo, monkeypatch, capsys):
    # Add and commit a non-test file, then modify it
    full = repo / "src" / "foo.py"
    full.parent.mkdir(parents=True)
    full.write_text("x = 1\n")
    subprocess.run(["git", "add", "src/foo.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    full.write_text("x = 2\n")
    subprocess.run(["git", "add", "src/foo.py"], cwd=repo, check=True)
    rc = _run(guard, _payload("git commit -m 'edit'", repo), monkeypatch)
    assert rc == 0


def test_passes_when_test_modified_not_deleted(guard, repo, monkeypatch):
    full = repo / "tests" / "test_a.py"
    full.parent.mkdir(parents=True)
    full.write_text("def test_x():\n    assert True\n")
    subprocess.run(["git", "add", "tests/test_a.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    full.write_text("def test_x():\n    assert 1 == 1\n")
    subprocess.run(["git", "add", "tests/test_a.py"], cwd=repo, check=True)
    rc = _run(guard, _payload("git commit -m 'edit test'", repo), monkeypatch)
    assert rc == 0


def test_passes_when_test_added(guard, repo, monkeypatch):
    _stage_add(repo, "tests/test_new.py", "def test_x(): pass\n")
    rc = _run(guard, _payload("git commit -m 'add test'", repo), monkeypatch)
    assert rc == 0


def test_override_via_trailer_in_inline_message(guard, repo, monkeypatch):
    _stage_delete(repo, "tests/test_legacy.py")
    cmd = "git commit -m 'remove obsolete suite\n\nOverride-Test-Deletion: replaced by integration tests'"
    rc = _run(guard, _payload(cmd, repo), monkeypatch)
    assert rc == 0


def test_override_via_env_var(guard, repo, monkeypatch):
    _stage_delete(repo, "tests/test_legacy.py")
    monkeypatch.setenv("DEVFLOW_OVERRIDE_TEST_DELETION", "1")
    rc = _run(guard, _payload("git commit -m 'cleanup'", repo), monkeypatch)
    assert rc == 0


def test_override_via_commit_file(guard, repo, monkeypatch):
    _stage_delete(repo, "tests/test_legacy.py")
    msg_file = repo / "MSG.txt"
    msg_file.write_text(
        "remove old\n\nOverride-Test-Deletion: superseded\n",
        encoding="utf-8",
    )
    cmd = f"git commit -F {msg_file}"
    rc = _run(guard, _payload(cmd, repo), monkeypatch)
    assert rc == 0


def test_disabled_via_config(guard, repo, monkeypatch, tmp_path):
    # Project-level disable
    (repo / ".devflow-config.json").write_text(
        json.dumps({"disabled_hooks": ["test_deletion_guard"]})
    )
    _stage_delete(repo, "tests/test_x.py")
    rc = _run(guard, _payload("git commit -m 'wipe'", repo), monkeypatch)
    assert rc == 0


def test_outside_repo_passes(guard, monkeypatch, tmp_path):
    rc = _run(guard, _payload("git commit -m 'x'", tmp_path), monkeypatch)
    assert rc == 0


def test_blocks_on_amend_with_staged_test_deletion(guard, repo, monkeypatch, capsys):
    """`git commit --amend` with staged test deletion must block too."""
    _stage_delete(repo, "tests/test_amend.py")
    rc = _run(guard, _payload("git commit --amend -m 'amend'", repo), monkeypatch)
    assert rc == 2
    assert "test_amend.py" in capsys.readouterr().err


def test_commit_graph_command_does_not_match(guard, repo, monkeypatch):
    """`git commit-graph write` is a different command — must NOT trigger."""
    _stage_delete(repo, "tests/test_x.py")
    rc = _run(guard, _payload("git commit-graph write", repo), monkeypatch)
    assert rc == 0
