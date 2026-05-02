"""Tests for pr_template.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "pr_template.py"


def _load():
    spec = importlib.util.spec_from_file_location("pr_template_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _payload(cwd: str, session: str = "test-session") -> str:
    return json.dumps({"cwd": cwd, "session_id": session})


def test_classify_fix_only(mod):
    assert mod._classify([("a", "fix(auth): nullcheck")]) == "fix"


def test_classify_feat_wins_over_fix(mod):
    commits = [("a", "feat: add x"), ("b", "fix: y")]
    assert mod._classify(commits) == "feat"


def test_classify_unknown_falls_back_chore(mod):
    assert mod._classify([("a", "freeform message")]) == "chore"


def test_default_body_includes_sections(mod):
    body = mod._build_default("feat", [("h", "feat: add login")], "1 file changed")
    assert "## What changed" in body
    assert "## Why" in body
    assert "## How to test" in body
    assert "## Risk / rollback" in body
    assert "feat: add login" in body
    assert "Behavior contract" not in body


def test_default_body_fix_includes_behavior_contract(mod):
    body = mod._build_default("fix", [("h", "fix: nullcheck")], "")
    assert "## Behavior contract" in body
    assert "CHANGES" in body
    assert "MUST NOT CHANGE" in body
    assert "PROOF" in body


def test_main_writes_draft_for_branch_with_commits(mod, tmp_path, monkeypatch):
    sys.stdin = io.StringIO(_payload(str(tmp_path), session="s1"))
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        ("log", "origin/main..HEAD", "--format=%h%x09%s"): "abc\tfeat: add x\ndef\tfix: y",
        ("diff", "--stat", "main...HEAD"): " 2 files changed",
    }
    import _stdin_cache
    _stdin_cache.reset()
    monkeypatch.setenv("DEVFLOW_LITE_HOME", str(tmp_path))
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        rc = mod.main()
    assert rc == 0
    out = tmp_path / ".claude" / "devflow-lite" / "state" / "s1" / "pr-draft.md"
    assert out.exists()
    text = out.read_text()
    assert "feat: add x" in text


def test_main_no_commits_noop(mod, tmp_path, monkeypatch):
    sys.stdin = io.StringIO(_payload(str(tmp_path), session="s2"))
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        ("log", "origin/main..HEAD", "--format=%h%x09%s"): "",
        ("log", "main..HEAD", "--format=%h%x09%s"): "",
    }
    import _stdin_cache
    _stdin_cache.reset()
    monkeypatch.setenv("DEVFLOW_LITE_HOME", str(tmp_path))
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        rc = mod.main()
    assert rc == 0
    assert not (tmp_path / ".claude" / "devflow-lite" / "state" / "s2" / "pr-draft.md").exists()


def test_repo_pr_template_used_when_present(mod, tmp_path, monkeypatch):
    (tmp_path / ".github").mkdir()
    custom = "## Repo template\n- a\n"
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(custom)
    sys.stdin = io.StringIO(_payload(str(tmp_path), session="s3"))
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        ("log", "origin/main..HEAD", "--format=%h%x09%s"): "abc\tfix: x",
        ("diff", "--stat", "main...HEAD"): "",
    }
    import _stdin_cache
    _stdin_cache.reset()
    monkeypatch.setenv("DEVFLOW_LITE_HOME", str(tmp_path))
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        mod.main()
    out = tmp_path / ".claude" / "devflow-lite" / "state" / "s3" / "pr-draft.md"
    assert out.read_text() == custom
