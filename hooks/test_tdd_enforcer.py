"""Tests for tdd_enforcer.py — focused on lite-era additions.

Scope: source-scope filter, hook-disabled kill-switch, vibe bypass.
The full AST/test-discovery matrix is covered by the legacy fixtures
elsewhere; this file pins behavior the user can reach via config.

Uses mkdtemp(prefix='devflow-') instead of pytest's tmp_path because
is_test_file() matches "test_" anywhere in the path string — pytest's
test-named tmp dirs would falsely flag every impl file as a test.
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


HOOK = Path(__file__).parent / "tdd_enforcer.py"


def _load():
    spec = importlib.util.spec_from_file_location("tdd_enforcer_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


@pytest.fixture
def workdir():
    d = Path(tempfile.mkdtemp(prefix="devflow-tddenf-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolate_state(workdir, monkeypatch):
    monkeypatch.setenv("DEVFLOW_STATE_DIR", str(workdir / "_state"))
    monkeypatch.setenv("DEVFLOW_SESSION_ID", "tdd-session-uuid-bbbbbbbbbbbb")
    sys.path.insert(0, str(HOOK.parent))
    import _stdin_cache
    _stdin_cache.reset()
    yield
    _stdin_cache.reset()


def _impl_payload(file_path: Path) -> str:
    return json.dumps({"tool_input": {"file_path": str(file_path)}})


def _make_repo(base: Path, src_subdir: str = "src") -> Path:
    repo = base / "repo"
    (repo / src_subdir).mkdir(parents=True)
    (repo / ".git").mkdir()
    return repo


def test_source_scope_filter_keeps_outside_src_silent(mod, workdir, capsys):
    repo = _make_repo(workdir)
    impl = repo / "scripts" / "deploy.py"
    impl.parent.mkdir(parents=True)
    impl.write_text("def go(): pass\n")
    sys.stdin = io.StringIO(_impl_payload(impl))
    rc = mod.main()
    assert rc == 0
    cap = capsys.readouterr()
    assert "CRITICAL WARNING" not in (cap.out + cap.err)


def test_source_scope_filter_warns_inside_src(mod, workdir, capsys):
    repo = _make_repo(workdir)
    impl = repo / "src" / "feature.py"
    impl.write_text("def go(): pass\n")
    sys.stdin = io.StringIO(_impl_payload(impl))
    rc = mod.main()
    assert rc == 0
    cap = capsys.readouterr()
    blob = cap.out + cap.err
    assert "CRITICAL WARNING" in blob, f"out={cap.out!r} err={cap.err!r}"
    assert "feature.py" in blob


def test_disabled_via_global_config(mod, workdir, monkeypatch, capsys):
    cfg_file = workdir / "devflow-config.json"
    cfg_file.write_text(json.dumps({"disabled_hooks": ["tdd_enforcer"]}))
    monkeypatch.setenv("DEVFLOW_CONFIG_FILE", str(cfg_file))
    repo = _make_repo(workdir)
    impl = repo / "src" / "feature.py"
    impl.write_text("def go(): pass\n")
    sys.stdin = io.StringIO(_impl_payload(impl))
    rc = mod.main()
    assert rc == 0
    cap = capsys.readouterr()
    assert "CRITICAL WARNING" not in (cap.out + cap.err)


def test_custom_source_dirs_via_global_config(mod, workdir, monkeypatch, capsys):
    cfg_file = workdir / "devflow-config.json"
    cfg_file.write_text(json.dumps({"tdd_enforcer_source_dirs": ["domain"]}))
    monkeypatch.setenv("DEVFLOW_CONFIG_FILE", str(cfg_file))
    repo = workdir / "repo"
    (repo / "domain").mkdir(parents=True)
    (repo / ".git").mkdir()
    impl = repo / "domain" / "user.py"
    impl.write_text("def x(): pass\n")
    sys.stdin = io.StringIO(_impl_payload(impl))
    rc = mod.main()
    assert rc == 0
    cap = capsys.readouterr()
    assert "CRITICAL WARNING" in (cap.out + cap.err)


def test_test_file_itself_silent(mod, workdir, capsys):
    repo = _make_repo(workdir)
    test_file = repo / "src" / "test_feature.py"
    test_file.write_text("def test_x(): pass\n")
    sys.stdin = io.StringIO(_impl_payload(test_file))
    rc = mod.main()
    assert rc == 0
    cap = capsys.readouterr()
    assert "CRITICAL WARNING" not in (cap.out + cap.err)


def test_is_in_source_scope_unit(mod):
    p = Path("/repo/src/feature.py")
    assert mod.is_in_source_scope(p, ["src", "lib"]) is True
    p2 = Path("/repo/scripts/deploy.py")
    assert mod.is_in_source_scope(p2, ["src", "lib"]) is False
    p3 = Path("/repo/anywhere.py")
    assert mod.is_in_source_scope(p3, []) is True
