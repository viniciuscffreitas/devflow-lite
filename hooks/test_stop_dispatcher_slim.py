"""Tests for stop_dispatcher_slim.py."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOK = Path(__file__).parent / "stop_dispatcher.py"


def _load():
    spec = importlib.util.spec_from_file_location("dispatcher_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


@pytest.fixture(autouse=True)
def _reset_stdin_cache():
    sys.path.insert(0, str(HOOK.parent))
    import _stdin_cache
    _stdin_cache.reset()
    yield
    _stdin_cache.reset()


def test_pipeline_order_is_phase_then_pr_then_judge(mod):
    assert mod._PIPELINE == ["spec_stop_guard", "phase_finalize", "pr_template", "post_task_judge"]


def test_run_calls_each_hook(mod, monkeypatch):
    sys.stdin = io.StringIO(json.dumps({"session_id": "x"}))
    calls: list[tuple[str, str]] = []

    def fake_run(name, stdin_data, session_id):
        calls.append((name, session_id))
        return 0

    monkeypatch.setattr(mod, "_run", fake_run)
    rc = mod.main()
    assert rc == 0
    assert [c[0] for c in calls] == [
        "spec_stop_guard",
        "phase_finalize",
        "pr_template",
        "post_task_judge",
    ]
    assert all(c[1] == "x" for c in calls)


def test_failing_hook_does_not_short_circuit(mod, monkeypatch):
    sys.stdin = io.StringIO("{}")
    calls: list[str] = []

    def fake_run(name, stdin_data, session_id):
        calls.append(name)
        return 2 if name == "phase_finalize" else 0

    monkeypatch.setattr(mod, "_run", fake_run)
    rc = mod.main()
    assert calls == ["spec_stop_guard", "phase_finalize", "pr_template", "post_task_judge"]
    assert rc == 2


def test_exception_in_hook_swallowed(mod, monkeypatch, capsys):
    sys.stdin = io.StringIO("{}")

    def boom_loader(_name, _path):
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib.util, "spec_from_file_location", boom_loader)
    rc = mod.main()
    assert rc == 0


def test_dispatcher_log_written_per_hook(mod, monkeypatch, tmp_path):
    sid = "11111111-2222-3333-4444-555555555555"
    sys.stdin = io.StringIO(json.dumps({"session_id": sid}))
    monkeypatch.setattr(mod, "_STATE_BASE", tmp_path)

    def patched_run(name, stdin_data, session_id):
        mod._log_hook(session_id, name, 0, 5, None)
        return 0

    monkeypatch.setattr(mod, "_run", patched_run)
    rc = mod.main()
    assert rc == 0
    log = tmp_path / sid / "dispatcher.log"
    assert log.exists(), (
        f"dispatcher.log missing under {tmp_path}; "
        f"contents={list(tmp_path.iterdir()) if tmp_path.exists() else 'no tmp'}"
    )
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert [e["hook"] for e in lines] == [
        "spec_stop_guard",
        "phase_finalize",
        "pr_template",
        "post_task_judge",
    ]
    assert all(isinstance(e["elapsed_ms"], int) for e in lines)


def test_dispatcher_log_skipped_for_default_session(mod, monkeypatch, tmp_path):
    sys.stdin = io.StringIO("{}")
    monkeypatch.setattr(mod, "_STATE_BASE", tmp_path)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)

    def patched_run(name, stdin_data, session_id):
        mod._log_hook(session_id, name, 0, 1, None)
        return 0

    monkeypatch.setattr(mod, "_run", patched_run)
    rc = mod.main()
    assert rc == 0
    # session_id falls back to "default" → log should NOT be created
    assert not any(tmp_path.iterdir()), "no log dir should be created for 'default' session"


def test_log_records_failure_with_error_string(mod, monkeypatch, tmp_path):
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    sys.stdin = io.StringIO(json.dumps({"session_id": sid}))
    monkeypatch.setattr(mod, "_STATE_BASE", tmp_path)

    def patched_run(name, stdin_data, session_id):
        mod._log_hook(session_id, name, 7, 12, "RuntimeError: boom")
        return 7

    monkeypatch.setattr(mod, "_run", patched_run)
    rc = mod.main()
    assert rc == 7
    log = tmp_path / sid / "dispatcher.log"
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert all(e["error"] == "RuntimeError: boom" for e in entries)
    assert all(e["rc"] == 7 for e in entries)
