"""Tests for spec_stop_guard.py."""
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


HOOK = Path(__file__).parent / "spec_stop_guard.py"


def _load(state_dir: Path):
    spec = importlib.util.spec_from_file_location("ssg_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STATE_DIR = state_dir
    return mod


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def _write_marker(state_dir: Path, sid: str, data: dict) -> Path:
    sdir = state_dir / sid
    sdir.mkdir(parents=True, exist_ok=True)
    target = sdir / "active-spec.json"
    target.write_text(json.dumps(data))
    return target


def _run(mod, payload, sid="sess-A"):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps(payload))
    env = {"CLAUDE_SESSION_ID": sid}
    captured = io.StringIO()
    with patch.dict(os.environ, env, clear=False), patch("sys.stdout", captured):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    return rc, captured.getvalue()


def test_no_marker_allows_exit(state):
    mod = _load(state)
    rc, out = _run(mod, {"cwd": "/repo"})
    assert rc == 0
    assert out == ""


def test_blocks_when_implementing(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    _write_marker(state, "sess-A", {
        "status": "IMPLEMENTING",
        "plan_path": "build feature X",
        "started_at": int(time.time()),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    payload = json.loads(out.strip())
    assert payload["decision"] == "block"
    assert "build feature X" in payload["reason"]
    assert "IMPLEMENTING" in payload["reason"]


def test_blocks_when_pending(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    _write_marker(state, "sess-A", {
        "status": "PENDING",
        "plan_path": "y",
        "started_at": int(time.time()),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert json.loads(out.strip())["decision"] == "block"


def test_completed_marker_is_deleted(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    marker = _write_marker(state, "sess-A", {
        "status": "COMPLETED",
        "plan_path": "z",
        "started_at": int(time.time()),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert out == ""
    assert not marker.exists()


def test_other_worktree_not_blocked(state, tmp_path):
    mod = _load(state)
    other = tmp_path / "other-worktree"
    other.mkdir()
    here = tmp_path / "here"
    here.mkdir()
    _write_marker(state, "sess-A", {
        "status": "IMPLEMENTING",
        "plan_path": "x",
        "started_at": int(time.time()),
        "cwd": str(other),
    })
    rc, out = _run(mod, {"cwd": str(here)})
    assert rc == 0
    assert out == ""


def test_stale_marker_does_not_block(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    _write_marker(state, "sess-A", {
        "status": "IMPLEMENTING",
        "plan_path": "old",
        "started_at": int(time.time()) - (25 * 3600),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert out == ""


def test_corrupt_marker_fails_open(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    sdir = state / "sess-A"
    sdir.mkdir(parents=True)
    (sdir / "active-spec.json").write_text("{not json")
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert out == ""


def test_default_session_id_passes(state):
    mod = _load(state)
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps({"cwd": "/repo"}))
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_SESSION_ID", "DEVFLOW_SESSION_ID")}
    captured = io.StringIO()
    with patch.dict(os.environ, env, clear=True), patch("sys.stdout", captured):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    assert rc == 0
    assert captured.getvalue() == ""


def test_unknown_status_does_not_block(state, tmp_path):
    mod = _load(state)
    cwd = str(tmp_path)
    _write_marker(state, "sess-A", {
        "status": "WAT",
        "plan_path": "x",
        "started_at": int(time.time()),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert out == ""


def test_aborted_status_does_not_block_exit(state, tmp_path):
    """devflow-agent writes ABORTED on kill; guard must let exit through."""
    mod = _load(state)
    cwd = str(tmp_path)
    marker = _write_marker(state, "sess-A", {
        "status": "ABORTED",
        "plan_path": "x",
        "started_at": int(time.time()),
        "cwd": cwd,
    })
    rc, out = _run(mod, {"cwd": cwd})
    assert rc == 0
    assert out == ""
    assert not marker.exists()
