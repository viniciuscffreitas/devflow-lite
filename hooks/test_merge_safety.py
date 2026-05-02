"""Tests for merge_safety.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "merge_safety.py"


def _load():
    spec = importlib.util.spec_from_file_location("merge_safety_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _run(mod, cmd, git_responses=None):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps({"tool_input": {"command": cmd}, "cwd": "/tmp"}))
    responses = git_responses or {}
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    return rc


def test_checkout_theirs_blocks(mod):
    assert _run(mod, "git checkout --theirs src/api.py") == 2


def test_checkout_ours_blocks(mod):
    assert _run(mod, "git checkout --ours src/api.py") == 2


def test_rebase_skip_blocks(mod):
    assert _run(mod, "git rebase --skip") == 2


def test_stash_drop_blocks(mod):
    assert _run(mod, "git stash drop stash@{0}") == 2


def test_stash_clear_blocks(mod):
    assert _run(mod, "git stash clear") == 2


def test_clean_force_blocks(mod):
    assert _run(mod, "git clean -fd") == 2


def test_clean_force_x_blocks(mod):
    assert _run(mod, "git clean -fdx") == 2


def test_reset_hard_with_foreign_authors_blocks(mod):
    responses = {
        ("config", "user.email"): "me@x.com",
        ("log", "--format=%ae", "HEAD~3..HEAD"): "alice@x.com\nme@x.com\nbob@x.com",
    }
    assert _run(mod, "git reset --hard HEAD~3", responses) == 2


def test_reset_hard_only_own_commits_passes(mod):
    responses = {
        ("config", "user.email"): "me@x.com",
        ("log", "--format=%ae", "HEAD~2..HEAD"): "me@x.com\nme@x.com",
    }
    assert _run(mod, "git reset --hard HEAD~2", responses) == 0


def test_checkout_conflicted_file_blocks(mod):
    responses = {
        ("diff", "--name-only", "--diff-filter=U"): "src/api.py\nsrc/auth.py",
    }
    assert _run(mod, "git checkout -- src/api.py", responses) == 2


def test_checkout_non_conflicted_passes(mod):
    responses = {
        ("diff", "--name-only", "--diff-filter=U"): "",
    }
    assert _run(mod, "git checkout -- src/clean.py", responses) == 0


def test_restore_conflicted_file_blocks(mod):
    responses = {
        ("diff", "--name-only", "--diff-filter=U"): "src/api.py",
    }
    assert _run(mod, "git restore src/api.py", responses) == 2


def test_non_git_command_noop(mod):
    assert _run(mod, "ls -la") == 0


def test_safe_git_command_passes(mod):
    assert _run(mod, "git status") == 0


def test_normal_checkout_branch_passes(mod):
    responses = {
        ("diff", "--name-only", "--diff-filter=U"): "",
    }
    assert _run(mod, "git checkout main", responses) == 0
