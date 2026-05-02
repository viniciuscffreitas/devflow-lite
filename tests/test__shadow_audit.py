"""Behavioral tests for ``hooks._shadow_audit``.

Coverage targets:
  * ``append_to_wiki_log`` writes to BOTH the per-project wiki and the
    central ``<devflow_root>/docs/wiki/log.md`` aggregator. When the two
    paths happen to coincide, only one write occurs (no duplicate line).
  * The header is written exactly once per file (idempotent first-write).
  * ``record_shadow_heal_failed`` adds a ``shadow_audit`` signal with
    ``event=heal_failed`` so JSONL drains preserve failed attempts too.
  * ``_consume_shadow_audits`` drains pending signals into
    ``state_dir/shadow_audit.jsonl`` AND mirrors ``healed`` events to the
    wiki log via ``append_to_wiki_log``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

import _shadow_audit as sa  # noqa: E402


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo-project"
    root.mkdir()
    return root


@pytest.fixture
def fake_devflow_root(tmp_path: Path, monkeypatch) -> Path:
    """Override ``_devflow_root`` so the central log lands under tmp_path."""
    central = tmp_path / "devflow-stub"
    central.mkdir()
    monkeypatch.setattr(sa, "_devflow_root", lambda: central)
    return central


def _read_lines(p: Path) -> list[str]:
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_append_writes_both_logs(
    project_root: Path, fake_devflow_root: Path,
) -> None:
    sa.append_to_wiki_log(project_root, "sess-1", "first event")
    project_log = project_root / "docs" / "wiki" / "log.md"
    central_log = fake_devflow_root / "docs" / "wiki" / "log.md"
    assert project_log.is_file()
    assert central_log.is_file()
    for path in (project_log, central_log):
        text = path.read_text(encoding="utf-8")
        assert "DevFlow Wiki — Self-Healing Audit Log" in text
        assert "sess-1" in text
        assert "first event" in text


def test_append_returns_project_path(
    project_root: Path, fake_devflow_root: Path,
) -> None:
    out = sa.append_to_wiki_log(project_root, "sess-1", "x")
    assert out == project_root / "docs" / "wiki" / "log.md"


def test_append_header_written_once(
    project_root: Path, fake_devflow_root: Path,
) -> None:
    sa.append_to_wiki_log(project_root, "sess-1", "a")
    sa.append_to_wiki_log(project_root, "sess-1", "b")
    project_log = project_root / "docs" / "wiki" / "log.md"
    text = project_log.read_text(encoding="utf-8")
    assert text.count("DevFlow Wiki — Self-Healing Audit Log") == 1
    body_lines = [ln for ln in _read_lines(project_log) if ln.startswith("- `")]
    assert len(body_lines) == 2


def test_append_dedup_when_paths_coincide(
    tmp_path: Path, monkeypatch,
) -> None:
    """If project_root == devflow_root, central write is skipped."""
    coincident = tmp_path / "shared"
    coincident.mkdir()
    monkeypatch.setattr(sa, "_devflow_root", lambda: coincident)
    sa.append_to_wiki_log(coincident, "sess-x", "single")
    log = coincident / "docs" / "wiki" / "log.md"
    body = [ln for ln in _read_lines(log) if ln.startswith("- `")]
    assert len(body) == 1


def test_record_shadow_heal_failed_adds_signal(monkeypatch) -> None:
    captured: list[dict] = []

    class _Store:
        def add_signal(self, session_id, kind, payload):
            captured.append({"sid": session_id, "kind": kind, "payload": payload})

    fake_module = type(sys)("telemetry.store")
    fake_module.get_store = lambda: _Store()
    fake_pkg = type(sys)("telemetry")
    fake_pkg.store = fake_module
    monkeypatch.setitem(sys.modules, "telemetry", fake_pkg)
    monkeypatch.setitem(sys.modules, "telemetry.store", fake_module)

    sa.record_shadow_heal_failed(
        "sess-fail", "max attempts hit", {"result": "fail", "heal_attempts": 3},
    )
    assert len(captured) == 1
    assert captured[0]["kind"] == "shadow_audit"
    payload = captured[0]["payload"]
    assert payload["event"] == "heal_failed"
    assert payload["summary"] == "max attempts hit"
    assert payload["verdict"]["heal_attempts"] == 3


def test_record_shadow_heal_failed_swallows_telemetry_errors(monkeypatch) -> None:
    """Telemetry must never propagate — gate stays green even on DB error."""
    fake = type(sys)("telemetry.store")
    def _boom():
        raise RuntimeError("db down")
    fake.get_store = _boom
    pkg = type(sys)("telemetry")
    pkg.store = fake
    monkeypatch.setitem(sys.modules, "telemetry", pkg)
    monkeypatch.setitem(sys.modules, "telemetry.store", fake)
    sa.record_shadow_heal_failed("sess", "summary", None)


def test_consume_shadow_audits_drains_to_jsonl(
    tmp_path: Path, project_root: Path, fake_devflow_root: Path, monkeypatch,
) -> None:
    state_dir = tmp_path / "state" / "sess-2"
    state_dir.mkdir(parents=True)

    signals = [
        {"payload": {
            "event": "healed", "source": "shadow_v3",
            "verdict": {"heal_attempts": 2, "snapshot_hash": "sha256:abc123def456"},
        }},
        {"payload": {
            "event": "heal_failed", "source": "shadow_v3",
            "summary": "no proposer",
            "verdict": {"heal_attempts": 3},
        }},
    ]

    class _Store:
        def consume_signals(self, sid: str, kind: str) -> list:
            assert sid == "sess-2"
            assert kind == "shadow_audit"
            return signals

    fake = type(sys)("telemetry.store")
    fake.get_store = lambda: _Store()
    pkg = type(sys)("telemetry")
    pkg.store = fake
    monkeypatch.setitem(sys.modules, "telemetry", pkg)
    monkeypatch.setitem(sys.modules, "telemetry.store", fake)

    out = sa._consume_shadow_audits(state_dir, project_root=project_root)
    assert out == []  # contract: returns [] so callers can concat fail-reasons

    jsonl = state_dir / "shadow_audit.jsonl"
    assert jsonl.is_file()
    rows = [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines()]
    assert {r["event"] for r in rows} == {"healed", "heal_failed"}

    project_log = project_root / "docs" / "wiki" / "log.md"
    central_log = fake_devflow_root / "docs" / "wiki" / "log.md"
    assert project_log.is_file()
    assert central_log.is_file()
    project_text = project_log.read_text(encoding="utf-8")
    assert "[HEALED]" in project_text  # healed event was mirrored
    assert "heal_failed" not in project_text  # only healed flows to wiki


def test_append_inserts_date_header(
    project_root: Path, fake_devflow_root: Path,
) -> None:
    sa.append_to_wiki_log(project_root, "sess-1", "x")
    sa.append_to_wiki_log(project_root, "sess-1", "y")
    log = project_root / "docs" / "wiki" / "log.md"
    text = log.read_text(encoding="utf-8")
    headers = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert len(headers) == 1
    assert headers[0].startswith("## 20")  # YYYY-MM-DD format


def test_ensure_date_header_idempotent_same_day() -> None:
    base = sa._WIKI_LOG_HEADER + "\n## 2026-04-25\n- entry\n"
    assert sa._ensure_date_header(base, "2026-04-25") == base


def test_ensure_date_header_appends_when_day_changes() -> None:
    base = sa._WIKI_LOG_HEADER + "\n## 2026-04-25\n- entry\n"
    out = sa._ensure_date_header(base, "2026-04-26")
    assert out.endswith("## 2026-04-26\n")
    assert out.count("## 2026-04-25") == 1


def test_consume_shadow_audits_handles_empty_drain(
    tmp_path: Path, monkeypatch,
) -> None:
    state_dir = tmp_path / "state" / "sess-empty"
    state_dir.mkdir(parents=True)
    fake = type(sys)("telemetry.store")
    fake.get_store = lambda: type("S", (), {"consume_signals": lambda *_a, **_k: []})()
    pkg = type(sys)("telemetry")
    pkg.store = fake
    monkeypatch.setitem(sys.modules, "telemetry", pkg)
    monkeypatch.setitem(sys.modules, "telemetry.store", fake)
    assert sa._consume_shadow_audits(state_dir) == []
    assert not (state_dir / "shadow_audit.jsonl").exists()
