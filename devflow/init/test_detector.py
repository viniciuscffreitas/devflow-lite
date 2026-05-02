"""Tests for devflow.init.detector."""
from __future__ import annotations

from pathlib import Path


from devflow.init.detector import Stack, detect_stack


class TestDetectStack:
    def test_generic_when_nothing_present(self, tmp_path: Path) -> None:
        assert detect_stack(tmp_path) is Stack.GENERIC

    def test_flutter_detected_via_pubspec(self, tmp_path: Path) -> None:
        (tmp_path / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
        assert detect_stack(tmp_path) is Stack.FLUTTER

    def test_python_wins_over_flutter_when_both_present(self, tmp_path: Path) -> None:
        (tmp_path / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        assert detect_stack(tmp_path) is Stack.PYTHON

    def test_node_wins_over_flutter_when_both_present(self, tmp_path: Path) -> None:
        (tmp_path / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert detect_stack(tmp_path) is Stack.NODE

    def test_flutter_wins_over_rust_and_go(self, tmp_path: Path) -> None:
        (tmp_path / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
        (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
        (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
        assert detect_stack(tmp_path) is Stack.FLUTTER

    def test_priority_order_frozen(self) -> None:
        """Regression guard: priority order is part of the public contract."""
        from devflow.init.detector import _DETECTORS
        order = [stack for stack, _markers in _DETECTORS]
        assert order == [Stack.PYTHON, Stack.NODE, Stack.FLUTTER, Stack.RUST, Stack.GO]
