"""Tests for pre_edit_overwrite_guard.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "pre_edit_overwrite_guard.py"


def _load():
    spec = importlib.util.spec_from_file_location("guard_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _run(mod, payload, git_responses=None):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps(payload))
    responses = git_responses or {}
    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")), \
         patch.object(mod, "_maybe_fetch", lambda r: None):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    return rc


def test_non_edit_tool_passes(mod):
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/tmp"}
    assert _run(mod, payload) == 0


def test_no_file_path_passes(mod):
    payload = {"tool_name": "Edit", "tool_input": {}, "cwd": "/tmp"}
    assert _run(mod, payload) == 0


def test_not_in_git_repo_passes(mod):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x.py"}, "cwd": "/tmp"}
    responses = {("rev-parse", "--show-toplevel"): ""}
    assert _run(mod, payload, responses) == 0


def test_no_upstream_passes(mod):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/repo/x.py"}, "cwd": "/repo"}
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "",
    }
    assert _run(mod, payload, responses) == 0


def test_file_outside_repo_passes(mod):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/elsewhere/x.py"}, "cwd": "/repo"}
    responses = {("rev-parse", "--show-toplevel"): "/repo"}
    assert _run(mod, payload, responses) == 0


def test_clean_upstream_passes(mod):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/x.py"}, "cwd": "/repo"}
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("log", "HEAD..origin/feat/x", "--oneline", "--", "src/x.py"): "",
    }
    assert _run(mod, payload, responses) == 0


def test_upstream_modified_blocks(mod):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/x.py"}, "cwd": "/repo"}
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("log", "HEAD..origin/feat/x", "--oneline", "--", "src/x.py"): "abc1234 alice work",
        ("log", "HEAD..origin/feat/x", "--format=%ae", "--", "src/x.py"): "alice@x.com",
        ("config", "user.email"): "me@x.com",
    }
    assert _run(mod, payload, responses) == 2


def test_upstream_modified_by_self_still_blocks(mod):
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/repo/src/x.py"}, "cwd": "/repo"}
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/main",
        ("log", "HEAD..origin/main", "--oneline", "--", "src/x.py"): "abc1234 my push from other machine",
        ("log", "HEAD..origin/main", "--format=%ae", "--", "src/x.py"): "me@x.com",
        ("config", "user.email"): "me@x.com",
    }
    assert _run(mod, payload, responses) == 2


def test_multiedit_blocked(mod):
    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": "/repo/src/x.py", "edits": [{"old_string": "a", "new_string": "b"}]},
        "cwd": "/repo",
    }
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("log", "HEAD..origin/feat/x", "--oneline", "--", "src/x.py"): "deadbee multiedit conflict",
        ("log", "HEAD..origin/feat/x", "--format=%ae", "--", "src/x.py"): "bob@x.com",
        ("config", "user.email"): "me@x.com",
    }
    assert _run(mod, payload, responses) == 2
