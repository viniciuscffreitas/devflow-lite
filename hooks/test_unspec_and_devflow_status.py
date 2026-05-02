"""Tests for scripts/unspec.py and scripts/devflow_status.py.

Co-located under hooks/ so the existing pytest discovery picks them up
without a separate scripts/conftest.py. Both scripts only touch
state files, so isolation via DEVFLOW_STATE_DIR is sufficient.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def state(tmp_path, monkeypatch):
    sdir = tmp_path / "state"
    sdir.mkdir()
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(sdir))
    sid = "abcdefab-1111-2222-3333-444444444444"
    monkeypatch.setenv("DEVFLOW_SESSION_ID", sid)
    monkeypatch.setenv("CLAUDE_SESSION_ID", sid)
    return sdir, sid


def test_unspec_removes_active_marker(state, capsys):
    sdir, sid = state
    session_dir = sdir / sid
    session_dir.mkdir()
    marker = session_dir / "active-spec.json"
    marker.write_text(json.dumps({"plan_path": "plans/feat.md", "status": "PENDING"}))
    mod = _load("unspec_under_test", SCRIPTS_DIR / "unspec.py")
    # Patch STATE_DIR since module captured Path.home() at import time
    mod.STATE_DIR = sdir
    rc = mod.main()
    assert rc == 0
    assert not marker.exists()
    out = capsys.readouterr().out
    assert "removed" in out and "plans/feat.md" in out


def test_unspec_idempotent_when_no_marker(state, capsys):
    sdir, _sid = state
    mod = _load("unspec_under_test_2", SCRIPTS_DIR / "unspec.py")
    mod.STATE_DIR = sdir
    rc = mod.main()
    assert rc == 0
    assert "no active spec" in capsys.readouterr().out


def test_devflow_status_runs_without_state(tmp_path, monkeypatch, capsys):
    sdir = tmp_path / "state-empty"
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(sdir))
    sid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setenv("CLAUDE_SESSION_ID", sid)
    monkeypatch.setenv("DEVFLOW_SESSION_ID", sid)
    mod = _load("devflow_status_under_test", SCRIPTS_DIR / "devflow_status.py")
    mod.STATE_DIR = sdir
    mod.LOCKS_DIR = sdir / "edit_locks"
    monkeypatch.setattr(sys, "argv", ["devflow_status.py", "status"])
    rc = mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "session:" in out
    assert "Active spec" in out


def test_devflow_status_lists_locks(state, monkeypatch, capsys):
    sdir, sid = state
    locks_dir = sdir / "edit_locks"
    locks_dir.mkdir()
    lock = locks_dir / "deadbeefdeadbeef.json"
    lock.write_text(
        json.dumps(
            {
                "path": "/tmp/foo.py",
                "session_id": sid,
                "pid": 999,
                "ts": 1700000000,
            }
        )
    )
    mod = _load("devflow_status_locks", SCRIPTS_DIR / "devflow_status.py")
    mod.STATE_DIR = sdir
    mod.LOCKS_DIR = locks_dir
    monkeypatch.setattr(sys, "argv", ["devflow_status.py", "locks"])
    rc = mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "/tmp/foo.py" in out
    assert "this session" in out


def test_devflow_status_unlock(state, monkeypatch, capsys, tmp_path):
    sdir, _sid = state
    locks_dir = sdir / "edit_locks"
    locks_dir.mkdir()
    target = tmp_path / "victim.py"
    target.write_text("x")
    mod = _load("devflow_status_unlock", SCRIPTS_DIR / "devflow_status.py")
    mod.STATE_DIR = sdir
    mod.LOCKS_DIR = locks_dir
    key = mod._lock_key_for(str(target))
    lock = locks_dir / f"{key}.json"
    lock.write_text(json.dumps({"path": str(target)}))
    monkeypatch.setattr(sys, "argv", ["devflow_status.py", "unlock", str(target)])
    rc = mod.main()
    assert rc == 0
    assert not lock.exists()
    assert "removed lock" in capsys.readouterr().out


def test_devflow_status_unknown_command(monkeypatch, capsys):
    mod = _load("devflow_status_unknown", SCRIPTS_DIR / "devflow_status.py")
    monkeypatch.setattr(sys, "argv", ["devflow_status.py", "bogus"])
    rc = mod.main()
    assert rc == 2
    assert "unknown" in capsys.readouterr().err
