"""Behavioral tests for ``agents.browser_operator``.

Coverage targets:
  * Markdown/text targets are wrapped into HTML and rasterized via the
    selected backend (Playwright preferred, html2image fallback).
  * Static images bypass HTML wrapping and are copied to the destination.
  * When no rasterizer is reachable, the shim raises a clear error AND
    leaves the HTML stub on disk for manual inspection.
  * Path/IO contracts: missing target raises FileNotFoundError; output
    parent dir is created automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

import agents.browser_operator as bo


@pytest.fixture(autouse=True)
def _restore_renderers(monkeypatch):
    """Force every test to choose a renderer explicitly."""
    monkeypatch.setattr(bo, "_render_with_playwright", lambda *_a, **_k: False)
    monkeypatch.setattr(bo, "_render_with_html2image", lambda *_a, **_k: False)
    yield


def test_missing_target_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bo.capture_screenshot(tmp_path / "nope.md", tmp_path / "out.png")


def test_image_passthrough_copies_bytes(tmp_path: Path) -> None:
    src = tmp_path / "icon.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    out = tmp_path / "deep" / "shot.png"
    result = bo.capture_screenshot(src, out)
    assert result == out
    assert out.read_bytes() == b"\x89PNG\r\n\x1a\nFAKE"


def test_html_wrap_uses_playwright_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    md = tmp_path / "log.md"
    md.write_text("# title\n- entry one\n", encoding="utf-8")
    out = tmp_path / "shot.png"

    captured: dict[str, Path] = {}

    def _fake_playwright(html_path: Path, out_path: Path) -> bool:
        captured["html"] = html_path
        captured["out"] = out_path
        out_path.write_bytes(b"PNGDATA")
        return True

    monkeypatch.setattr(bo, "_render_with_playwright", _fake_playwright)
    result = bo.capture_screenshot(md, out)
    assert result == out
    assert out.read_bytes() == b"PNGDATA"
    html_text = captured["html"].read_text(encoding="utf-8")
    assert "title" in html_text
    assert "entry one" in html_text
    assert "<style>" in html_text


def test_falls_back_to_html2image(tmp_path: Path, monkeypatch) -> None:
    md = tmp_path / "log.md"
    md.write_text("body", encoding="utf-8")
    out = tmp_path / "out.png"

    def _fake_html2image(html_path: Path, out_path: Path) -> bool:
        out_path.write_bytes(b"H2I")
        return True

    monkeypatch.setattr(bo, "_render_with_html2image", _fake_html2image)
    bo.capture_screenshot(md, out)
    assert out.read_bytes() == b"H2I"


def test_no_renderer_available_raises_and_leaves_stub(tmp_path: Path) -> None:
    md = tmp_path / "log.md"
    md.write_text("# stub", encoding="utf-8")
    out = tmp_path / "out.png"
    with pytest.raises(bo.BrowserOperatorUnavailable):
        bo.capture_screenshot(md, out)
    stub = out.with_suffix(".html")
    assert stub.is_file()
    assert "stub" in stub.read_text(encoding="utf-8")


def test_html_escapes_angle_brackets(tmp_path: Path, monkeypatch) -> None:
    md = tmp_path / "log.md"
    md.write_text("<script>alert('x')</script>", encoding="utf-8")
    out = tmp_path / "out.png"
    captured: dict[str, Path] = {}

    def _fake(html_path: Path, out_path: Path) -> bool:
        captured["html"] = html_path
        out_path.write_bytes(b"OK")
        return True

    monkeypatch.setattr(bo, "_render_with_playwright", _fake)
    bo.capture_screenshot(md, out)
    body = captured["html"].read_text(encoding="utf-8")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_browser_operator_alias_is_capture_screenshot() -> None:
    assert bo.browser_operator is bo.capture_screenshot


def test_render_with_playwright_returns_false_when_missing(monkeypatch) -> None:
    """Importing playwright must not crash the shim if absent."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    assert bo._render_with_playwright(Path("/nope"), Path("/nope")) is False


def test_render_with_html2image_returns_false_when_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "html2image", None)
    assert bo._render_with_html2image(Path("/nope"), Path("/nope")) is False


def test_html2image_success_uses_real_module(tmp_path: Path, monkeypatch) -> None:
    """html2image branch wires output_path + filename correctly."""
    import importlib

    out = tmp_path / "shot.png"
    fake = ModuleType("html2image")

    class _Fake:
        def __init__(self, output_path: str) -> None:
            self.output_path = output_path

        def screenshot(self, *, html_file: str, save_as: str, size: tuple[int, int]) -> None:
            (Path(self.output_path) / save_as).write_bytes(b"FAKE")

    fake.Html2Image = _Fake
    monkeypatch.setitem(sys.modules, "html2image", fake)
    real = importlib.reload(bo)
    html = tmp_path / "src.html"
    html.write_text("<html></html>", encoding="utf-8")
    try:
        assert real._render_with_html2image(html, out) is True
        assert out.read_bytes() == b"FAKE"
    finally:
        importlib.reload(bo)
