"""Tests for concurrent_edit_lock.py."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "concurrent_edit_lock.py"


def _load(locks_dir: Path):
    spec = importlib.util.spec_from_file_location("lock_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.LOCKS_DIR = locks_dir
    return mod


@pytest.fixture
def locks(tmp_path):
    d = tmp_path / "locks"
    return d


def _payload(event, file_path, tool="Edit"):
    return {
        "hook_event_name": event,
        "tool_name": tool,
        "tool_input": {"file_path": file_path},
    }


def _run(mod, payload, sid="sess-A"):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps(payload))
    env = {"CLAUDE_SESSION_ID": sid}
    with patch.dict(os.environ, env, clear=False):
        try:
            return mod.main()
        except SystemExit as e:
            return int(e.code or 0)


def test_acquire_when_no_lock(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    rc = _run(mod, _payload("PreToolUse", str(f)))
    assert rc == 0
    lock = mod._lock_path(str(f))
    assert lock.exists()
    data = json.loads(lock.read_text())
    assert data["session_id"] == "sess-A"


def test_block_when_other_session_holds_fresh_lock(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    rc = _run(mod, _payload("PreToolUse", str(f)), sid="sess-B")
    assert rc == 2


def test_same_session_reuses_lock(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    rc = _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    assert rc == 0


def test_release_removes_own_lock(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    lock = mod._lock_path(str(f))
    assert lock.exists()
    _run(mod, _payload("PostToolUse", str(f)), sid="sess-A")
    assert not lock.exists()


def test_release_does_not_remove_other_session_lock(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    _run(mod, _payload("PostToolUse", str(f)), sid="sess-B")
    assert mod._lock_path(str(f)).exists()


def test_stale_lock_taken_over(locks, tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a")
    mod = _load(locks)
    locks.mkdir(parents=True, exist_ok=True)
    stale = mod._lock_path(str(f))
    stale.write_text(json.dumps({
        "session_id": "sess-OLD",
        "pid": 1,
        "ts": time.time() - 9999,
        "path": str(f),
    }))
    rc = _run(mod, _payload("PreToolUse", str(f)), sid="sess-A")
    assert rc == 0
    data = json.loads(stale.read_text())
    assert data["session_id"] == "sess-A"


def test_non_edit_tool_passes(locks, tmp_path):
    mod = _load(locks)
    rc = _run(mod, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "ls"}})
    assert rc == 0


def test_no_file_path_passes(locks):
    mod = _load(locks)
    rc = _run(mod, {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                    "tool_input": {}})
    assert rc == 0


def test_realpath_collision_detected(locks, tmp_path):
    """Symlink and real path point to same file → same lock key."""
    real = tmp_path / "real.py"
    real.write_text("a")
    link = tmp_path / "link.py"
    link.symlink_to(real)
    mod = _load(locks)
    _run(mod, _payload("PreToolUse", str(real)), sid="sess-A")
    rc = _run(mod, _payload("PreToolUse", str(link)), sid="sess-B")
    assert rc == 2
