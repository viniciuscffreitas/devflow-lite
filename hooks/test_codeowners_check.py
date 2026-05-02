"""Tests for codeowners_check.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "codeowners_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("codeowners_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(tmp_path / "_state"))
    monkeypatch.setenv("DEVFLOW_SESSION_ID", "default-test-session-uuid-aaaaaa")


def _setup_repo(tmp_path: Path, codeowners_text: str | None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir()
    if codeowners_text is not None:
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "CODEOWNERS").write_text(codeowners_text)
    return tmp_path


def _run(mod, repo: Path, file_rel: str, git_email: str = ""):
    import _stdin_cache
    _stdin_cache.reset()
    target = repo / file_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x")
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    sys.stdin = io.StringIO(payload)
    with patch.object(mod, "_git", return_value=git_email):
        return mod.main()


def test_no_codeowners_silent(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, None)
    rc = _run(mod, repo, "src/foo.py")
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_match_foreign_owner_warns(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, "/payments/ @alice @charlie\n")
    rc = _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    out = capsys.readouterr().out
    assert rc == 0
    assert "[devflow:codeowners]" in out
    assert "@alice" in out


def test_match_self_owner_silent(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, "/payments/ @alice\n")
    rc = _run(mod, repo, "payments/api.py", git_email="alice@x.com")
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_glob_double_star(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, "/lib/**/auth/* @sec\n")
    rc = _run(mod, repo, "lib/features/foo/auth/login.dart", git_email="me@x.com")
    out = capsys.readouterr().out
    assert "@sec" in out


def test_no_match_silent(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, "/payments/ @alice\n")
    rc = _run(mod, repo, "src/unrelated.py", git_email="bob@x.com")
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_comments_and_blanks_ignored(mod, tmp_path, capsys):
    repo = _setup_repo(tmp_path, "# header\n\n/payments/ @alice\n")
    rc = _run(mod, repo, "payments/x.py", git_email="bob@x.com")
    assert "@alice" in capsys.readouterr().out


def test_dedup_same_file_within_session(mod, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DEVFLOW_SESSION_ID", "11111111-aaaa-bbbb-cccc-222222222222")
    repo = _setup_repo(tmp_path / "repo", "/payments/ @alice\n")
    rc1 = _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    out1 = capsys.readouterr().out
    rc2 = _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    out2 = capsys.readouterr().out
    assert rc1 == 0 and rc2 == 0
    assert "@alice" in out1, "first edit should warn"
    assert "@alice" not in out2, "second edit on same file should be deduped"


def test_dedup_disabled_via_config(mod, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DEVFLOW_SESSION_ID", "22222222-aaaa-bbbb-cccc-333333333333")
    repo = _setup_repo(tmp_path / "repo", "/payments/ @alice\n")
    cfg = repo / ".devflow-config.json"
    cfg.write_text(json.dumps({"codeowners_dedup_per_session": False}))
    _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    out1 = capsys.readouterr().out
    _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    out2 = capsys.readouterr().out
    assert "@alice" in out1
    assert "@alice" in out2, "dedup disabled — should warn each time"


def test_disabled_via_config(mod, tmp_path, monkeypatch, capsys):
    cfg_file = tmp_path / "devflow-config.json"
    cfg_file.write_text(json.dumps({"disabled_hooks": ["codeowners_check"]}))
    monkeypatch.setenv("DEVFLOW_CONFIG_FILE", str(cfg_file))
    repo = _setup_repo(tmp_path / "repo", "/payments/ @alice\n")
    rc = _run(mod, repo, "payments/api.py", git_email="bob@x.com")
    assert rc == 0
    out = capsys.readouterr().out
    assert "[devflow:codeowners]" not in out
