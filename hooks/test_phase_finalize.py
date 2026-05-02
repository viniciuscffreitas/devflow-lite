"""Tests for phase_finalize.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


HOOK = Path(__file__).parent / "phase_finalize.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase_finalize_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _reset_cache():
    import _stdin_cache
    _stdin_cache.reset()


def test_writes_phase_record(mod, tmp_path, monkeypatch):
    _reset_cache()
    sys.stdin = io.StringIO(json.dumps({"session_id": "abc", "cwd": "/x"}))
    monkeypatch.setenv("DEVFLOW_LITE_HOME", str(tmp_path))
    rc = mod.main()
    assert rc == 0
    out = tmp_path / ".claude" / "devflow-lite" / "state" / "abc" / "phase.json"
    assert out.exists()
    record = json.loads(out.read_text())
    assert record["session_id"] == "abc"
    assert record["phase"] == "COMPLETED"
    assert record["cwd"] == "/x"
    assert isinstance(record["completed_at"], int)


def test_missing_session_uses_default(mod, tmp_path, monkeypatch):
    _reset_cache()
    sys.stdin = io.StringIO("{}")
    monkeypatch.setenv("DEVFLOW_LITE_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    rc = mod.main()
    assert rc == 0
    assert (tmp_path / ".claude" / "devflow-lite" / "state" / "default" / "phase.json").exists()
