"""Tests for repo_conventions.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "repo_conventions.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_conv_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def test_outside_git_repo_noop(mod, capsys, monkeypatch):
    monkeypatch.chdir("/tmp")
    with patch.object(mod, "_git", return_value=""):
        assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_detects_gitflow(mod, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    branches = "main\norigin/main\norigin/develop\norigin/release/1.0\n"
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("branch", "-a", "--format=%(refname:short)"): branches,
        ("config", "--get", "pull.rebase"): "true",
        ("config", "--get", "commit.gpgsign"): "false",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
    }
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        mod.main()
    out = capsys.readouterr().out
    assert "workflow=gitflow" in out
    assert "default_branch=main" in out
    assert "pull_rebase=true" in out


def test_detects_github_flow_with_pr_template(mod, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("# PR\n")
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("branch", "-a", "--format=%(refname:short)"): "main\norigin/main\n",
        ("config", "--get", "pull.rebase"): "",
        ("config", "--get", "commit.gpgsign"): "",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
    }
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        mod.main()
    out = capsys.readouterr().out
    assert "workflow=github-flow" in out
    assert "pr_template=.github/PULL_REQUEST_TEMPLATE.md" in out


def test_codeowners_detected(mod, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("* @team\n")
    responses = {
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("branch", "-a", "--format=%(refname:short)"): "main\n",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
    }
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        mod.main()
    assert "codeowners=yes" in capsys.readouterr().out
