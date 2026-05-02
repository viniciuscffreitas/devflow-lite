"""Tests for freshness_check.py."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "freshness_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("freshness_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _run(mod, git_responses=None, fetch_called=None):
    responses = git_responses or {}
    calls: list[tuple] = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    with patch.object(mod, "_git", side_effect=lambda *a, **kw: responses.get(a, "")), \
         patch.object(mod.subprocess, "run", side_effect=fake_run), \
         patch.object(mod, "_record_fetch", lambda r: None):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    if fetch_called is not None:
        fetch_called.extend(calls)
    return rc


def test_not_in_repo_passes(mod, capsys):
    rc = _run(mod, {("rev-parse", "--show-toplevel"): ""})
    assert rc == 0
    assert "freshness" not in capsys.readouterr().out


def test_repo_no_upstream_emits_status(mod, capsys):
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "",
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
    }
    rc = _run(mod, responses)
    out = capsys.readouterr().out
    assert rc == 0
    assert "branch=feat/x" in out
    assert "upstream=none" in out


def test_behind_upstream_warns(mod, capsys):
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("rev-list", "--count", "HEAD..origin/feat/x"): "2",
        ("rev-list", "--count", "origin/feat/x..HEAD"): "1",
        ("log", "HEAD..origin/feat/x", "--name-only", "--format="): "src/a.py\nsrc/b.py",
    }
    rc = _run(mod, responses)
    out = capsys.readouterr().out
    assert rc == 0
    assert "behind=2" in out
    assert "WARN" in out
    assert "src/a.py" in out


def test_in_sync_no_warn(mod, capsys):
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("rev-list", "--count", "HEAD..origin/feat/x"): "0",
        ("rev-list", "--count", "origin/feat/x..HEAD"): "0",
    }
    rc = _run(mod, responses)
    out = capsys.readouterr().out
    assert rc == 0
    assert "behind=0" in out
    assert "WARN" not in out


def test_skips_fetch_when_cache_fresh(mod, capsys):
    import time as _t

    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("rev-list", "--count", "HEAD..origin/feat/x"): "0",
        ("rev-list", "--count", "origin/feat/x..HEAD"): "0",
    }
    calls: list[tuple] = []
    with patch.object(mod, "_last_fetch", lambda _r: _t.time() - 30):
        rc = _run(mod, responses, fetch_called=calls)
    assert rc == 0
    assert all("fetch" not in " ".join(c) for c in calls)


def test_fetches_when_cache_stale(mod, capsys):
    responses = {
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "--abbrev-ref", "@{u}"): "origin/feat/x",
        ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("rev-list", "--count", "HEAD..origin/feat/x"): "0",
        ("rev-list", "--count", "origin/feat/x..HEAD"): "0",
    }
    calls: list[tuple] = []
    with patch.object(mod, "_last_fetch", lambda _r: 0.0):
        rc = _run(mod, responses, fetch_called=calls)
    assert rc == 0
    assert any("fetch" in " ".join(c) for c in calls), \
        "should fetch when cache is stale"


def test_disabled_via_config(mod, monkeypatch, capsys):
    responses = {("rev-parse", "--show-toplevel"): "/repo"}
    import _util
    monkeypatch.setattr(_util, "is_hook_disabled", lambda *a, **kw: True)
    rc = _run(mod, responses)
    assert rc == 0
    assert "freshness" not in capsys.readouterr().out
