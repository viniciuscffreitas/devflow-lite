"""Tests for branch_policy.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "branch_policy.py"


def _load():
    spec = importlib.util.spec_from_file_location("branch_policy_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(cmd: str) -> str:
    return json.dumps({"tool_input": {"command": cmd}, "cwd": "/tmp"})


@pytest.fixture
def mod():
    return _load()


def _run(mod, cmd, git_responses):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(_payload(cmd))
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: git_responses.get(a, "")):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    return rc


def test_push_to_main_blocks(mod):
    rc = _run(mod, "git push origin main", {})
    assert rc == 2


def test_push_to_master_blocks(mod):
    rc = _run(mod, "git push origin master", {})
    assert rc == 2


def test_push_to_release_branch_blocks(mod):
    rc = _run(mod, "git push origin release/1.2.0", {})
    assert rc == 2


def test_plain_force_blocks(mod):
    rc = _run(mod, "git push --force origin feat/x", {
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
    })
    assert rc == 2


def test_force_with_lease_own_branch_passes(mod):
    rc = _run(mod, "git push --force-with-lease origin feat/x", {
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("log", "-1", "--format=%ae"): "me@x.com",
        ("config", "user.email"): "me@x.com",
    })
    assert rc == 0


def test_force_with_lease_foreign_author_blocks(mod):
    rc = _run(mod, "git push --force-with-lease origin feat/x", {
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("log", "-1", "--format=%ae"): "alice@x.com",
        ("config", "user.email"): "bob@x.com",
    })
    assert rc == 2


def test_set_upstream_bad_branch_warns_not_block(mod, capsys):
    rc = _run(mod, "git push -u origin random-name", {
        ("rev-parse", "--abbrev-ref", "HEAD"): "random-name",
    })
    assert rc == 0
    out = capsys.readouterr().out
    assert "lacks conventional prefix" in out


def test_set_upstream_good_branch_silent(mod, capsys):
    rc = _run(mod, "git push -u origin feat/auth-refresh", {
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/auth-refresh",
    })
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_non_push_command_noop(mod):
    rc = _run(mod, "git status", {})
    assert rc == 0
