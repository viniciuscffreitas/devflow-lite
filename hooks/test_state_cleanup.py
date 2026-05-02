"""Tests for state_cleanup.py."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest


HOOK = Path(__file__).parent / "state_cleanup.py"


def _load(state_dir: Path):
    spec = importlib.util.spec_from_file_location("state_cleanup_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.STATE_DIR = state_dir
    mod.CACHE_FILE = state_dir / "freshness_cache.json"
    return mod


@pytest.fixture
def state(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _make_session(state_dir, uuid, age_seconds):
    s = state_dir / uuid
    s.mkdir()
    (s / "phase.json").write_text("{}")
    mtime = time.time() - age_seconds
    import os
    os.utime(s, (mtime, mtime))
    return s


def test_prunes_old_sessions(state):
    mod = _load(state)
    fresh = _make_session(state, "11111111-aaaa-bbbb-cccc-222222222222", 60)
    stale = _make_session(state, "33333333-dddd-eeee-ffff-444444444444", 30 * 86400)
    rc = mod.main()
    assert rc == 0
    assert fresh.exists()
    assert not stale.exists()


def test_keeps_non_uuid_dirs(state):
    mod = _load(state)
    (state / "default").mkdir()
    (state / "default" / "x.json").write_text("{}")
    import os
    mtime = time.time() - 30 * 86400
    os.utime(state / "default", (mtime, mtime))
    rc = mod.main()
    assert rc == 0
    assert (state / "default").exists()


def test_no_state_dir_passes(tmp_path):
    mod = _load(tmp_path / "missing")
    assert mod.main() == 0


def test_trims_freshness_cache_old_entries(state):
    mod = _load(state)
    now = time.time()
    cache = {
        "/repo/a": now - 60,
        "/repo/b": now - 30 * 86400,
    }
    (state / "freshness_cache.json").write_text(json.dumps(cache))
    rc = mod.main()
    assert rc == 0
    saved = json.loads((state / "freshness_cache.json").read_text())
    assert "/repo/a" in saved
    assert "/repo/b" not in saved


def test_trims_freshness_cache_size_cap(state):
    mod = _load(state)
    now = time.time()
    cache = {f"/repo/{i}": now - i for i in range(80)}
    (state / "freshness_cache.json").write_text(json.dumps(cache))
    rc = mod.main()
    assert rc == 0
    saved = json.loads((state / "freshness_cache.json").read_text())
    assert len(saved) == mod.CACHE_MAX_REPOS


def test_corrupt_cache_handled(state):
    mod = _load(state)
    (state / "freshness_cache.json").write_text("{ not json")
    assert mod.main() == 0


def test_prunes_by_started_at_even_if_mtime_fresh(state):
    mod = _load(state)
    import os
    s = state / "55555555-aaaa-bbbb-cccc-666666666666"
    s.mkdir()
    old = time.time() - 30 * 86400
    (s / "active-spec.json").write_text(
        json.dumps({"status": "PENDING", "started_at": old, "plan_path": "x"})
    )
    now = time.time()
    os.utime(s, (now, now))
    rc = mod.main()
    assert rc == 0
    assert not s.exists(), "should prune by started_at, ignoring fresh mtime"


def test_keeps_when_completed_at_fresh(state):
    mod = _load(state)
    import os
    s = state / "77777777-aaaa-bbbb-cccc-888888888888"
    s.mkdir()
    fresh_ts = time.time() - 60
    (s / "phase.json").write_text(
        json.dumps({"phase": "COMPLETED", "completed_at": fresh_ts})
    )
    old = time.time() - 30 * 86400
    os.utime(s, (old, old))
    rc = mod.main()
    assert rc == 0
    assert s.exists(), "fresh completed_at should keep session despite stale mtime"


def test_prunes_by_completed_at_old(state):
    mod = _load(state)
    s = state / "99999999-aaaa-bbbb-cccc-000000000000"
    s.mkdir()
    old = time.time() - 30 * 86400
    (s / "phase.json").write_text(
        json.dumps({"phase": "COMPLETED", "completed_at": old})
    )
    rc = mod.main()
    assert rc == 0
    assert not s.exists()
