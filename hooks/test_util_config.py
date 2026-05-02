"""Tests for _util config knobs (load_devflow_config, is_hook_disabled).

Pins lite-era defaults (disabled_hooks, freshness_fetch_ttl, dedup, etc.)
so a typo in defaults can't silently disable a hook for everyone.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


HOOKS_DIR = Path(__file__).parent
sys.path.insert(0, str(HOOKS_DIR))


@pytest.fixture
def util(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVFLOW_ROOT", str(tmp_path / "devflow"))
    monkeypatch.setenv("DEVFLOW_CONFIG_FILE", str(tmp_path / "global-config.json"))
    if "_util" in sys.modules:
        importlib.reload(sys.modules["_util"])
    import _util
    return _util


def test_defaults_present(util):
    cfg = util.load_devflow_config()
    assert cfg["learned_skills_auto_inject"] is True
    assert cfg["disabled_hooks"] == []
    assert cfg["freshness_fetch_ttl"] == 300
    assert cfg["discovery_scan_ttl"] == 86400
    assert cfg["codeowners_dedup_per_session"] is True
    assert "src" in cfg["tdd_enforcer_source_dirs"]


def test_global_overrides_defaults(util, tmp_path):
    cfg_file = Path(tmp_path) / "global-config.json"
    cfg_file.write_text(
        json.dumps({"freshness_fetch_ttl": 7, "disabled_hooks": ["foo_hook"]})
    )
    # Re-resolve: load_devflow_config reads via current_paths() which is not cached
    cfg = util.load_devflow_config()
    assert cfg["freshness_fetch_ttl"] == 7
    assert cfg["disabled_hooks"] == ["foo_hook"]
    # Untouched defaults still present
    assert cfg["codeowners_dedup_per_session"] is True


def test_project_overrides_global(util, tmp_path):
    global_cfg = Path(tmp_path) / "global-config.json"
    global_cfg.write_text(json.dumps({"freshness_fetch_ttl": 100}))
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".devflow-config.json").write_text(
        json.dumps({"freshness_fetch_ttl": 999})
    )
    cfg = util.load_devflow_config(project)
    assert cfg["freshness_fetch_ttl"] == 999


def test_is_hook_disabled_reads_global(util, tmp_path):
    cfg_file = Path(tmp_path) / "global-config.json"
    cfg_file.write_text(json.dumps({"disabled_hooks": ["tdd_enforcer"]}))
    assert util.is_hook_disabled("tdd_enforcer") is True
    assert util.is_hook_disabled("freshness_check") is False


def test_is_hook_disabled_corrupt_config_safe(util, tmp_path):
    cfg_file = Path(tmp_path) / "global-config.json"
    cfg_file.write_text("{ not json")
    assert util.is_hook_disabled("anything") is False


def test_is_hook_disabled_empty_list(util):
    assert util.is_hook_disabled("anything") is False
