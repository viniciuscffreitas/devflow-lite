"""Tests for spec_phase_tracker.py."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "spec_phase_tracker.py"


def _load(state_dir: Path):
    spec = importlib.util.spec_from_file_location("spt_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STATE_DIR = state_dir
    return mod


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def _run(mod, payload, sid="sess-A", cwd="/repo"):
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps(payload))
    env = {"CLAUDE_SESSION_ID": sid}
    with patch.dict(os.environ, env, clear=False):
        try:
            return mod.main()
        except SystemExit as e:
            return int(e.code or 0)


def test_writes_pending_on_spec_command(state, tmp_path):
    mod = _load(state)
    payload = {"prompt": "/spec add pagination", "cwd": str(tmp_path)}
    rc = _run(mod, payload)
    assert rc == 0
    marker = state / "sess-A" / "active-spec.json"
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["status"] == "PENDING"
    assert data["plan_path"] == "add pagination"
    assert data["cwd"] == str(tmp_path)
    assert isinstance(data["started_at"], int)


def test_no_op_when_prompt_lacks_spec(state):
    mod = _load(state)
    rc = _run(mod, {"prompt": "just chatting", "cwd": "/repo"})
    assert rc == 0
    assert not (state / "sess-A").exists()


def test_strips_quotes_from_description(state):
    mod = _load(state)
    rc = _run(mod, {"prompt": '/spec "fix login bug"', "cwd": "/repo"})
    assert rc == 0
    data = json.loads((state / "sess-A" / "active-spec.json").read_text())
    assert data["plan_path"] == "fix login bug"


def test_unnamed_when_no_description(state):
    mod = _load(state)
    rc = _run(mod, {"prompt": "/spec", "cwd": "/repo"})
    assert rc == 0
    data = json.loads((state / "sess-A" / "active-spec.json").read_text())
    assert data["plan_path"] == "unnamed spec"


def test_session_id_from_payload_when_env_absent(state):
    mod = _load(state)
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps(
        {"prompt": "/spec x", "cwd": "/repo", "session_id": "from-payload"}
    ))
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_SESSION_ID", "DEVFLOW_SESSION_ID")}
    with patch.dict(os.environ, env, clear=True):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    assert rc == 0
    assert (state / "from-payload" / "active-spec.json").exists()


def test_default_session_when_no_id(state):
    mod = _load(state)
    import _stdin_cache
    _stdin_cache.reset()
    sys.stdin = io.StringIO(json.dumps({"prompt": "/spec x", "cwd": "/repo"}))
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_SESSION_ID", "DEVFLOW_SESSION_ID")}
    with patch.dict(os.environ, env, clear=True):
        try:
            rc = mod.main()
        except SystemExit as e:
            rc = int(e.code or 0)
    assert rc == 0
    assert (state / "default" / "active-spec.json").exists()


def test_atomic_write_no_temp_left(state, tmp_path):
    mod = _load(state)
    rc = _run(mod, {"prompt": "/spec x", "cwd": str(tmp_path)})
    assert rc == 0
    sdir = state / "sess-A"
    leftovers = [p for p in sdir.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_overwrites_previous_marker(state, tmp_path):
    mod = _load(state)
    _run(mod, {"prompt": "/spec first", "cwd": str(tmp_path)})
    _run(mod, {"prompt": "/spec second", "cwd": str(tmp_path)})
    data = json.loads((state / "sess-A" / "active-spec.json").read_text())
    assert data["plan_path"] == "second"
