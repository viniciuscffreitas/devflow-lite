"""Tests for devflow.main — RLIMIT_NOFILE OS guard."""
from __future__ import annotations

import io
import resource

from devflow import main as dm


class TestCheckFdLimit:
    def test_returns_true_above_threshold(self, monkeypatch):
        monkeypatch.setattr(
            dm.resource, "getrlimit",
            lambda _: (8192, 8192),
        )
        buf = io.StringIO()
        assert dm.check_fd_limit(stream=buf) is True
        assert buf.getvalue() == ""

    def test_returns_true_at_threshold(self, monkeypatch):
        monkeypatch.setattr(
            dm.resource, "getrlimit",
            lambda _: (dm._FD_LIMIT_RECOMMENDED, dm._FD_LIMIT_RECOMMENDED),
        )
        buf = io.StringIO()
        assert dm.check_fd_limit(stream=buf) is True
        assert buf.getvalue() == ""

    def test_returns_false_and_warns_below_threshold(self, monkeypatch):
        monkeypatch.setattr(
            dm.resource, "getrlimit",
            lambda _: (256, 4096),
        )
        buf = io.StringIO()
        assert dm.check_fd_limit(stream=buf) is False
        msg = buf.getvalue()
        assert "RLIMIT_NOFILE" in msg
        assert "256" in msg
        assert str(dm._FD_LIMIT_RECOMMENDED) in msg

    def test_swallows_resource_errors(self, monkeypatch):
        def boom(_):
            raise OSError("simulated")

        monkeypatch.setattr(dm.resource, "getrlimit", boom)
        buf = io.StringIO()
        assert dm.check_fd_limit(stream=buf) is True
        assert buf.getvalue() == ""

    def test_uses_rlimit_nofile_constant(self, monkeypatch):
        captured: dict = {}

        def fake_getrlimit(which):
            captured["which"] = which
            return (8192, 8192)

        monkeypatch.setattr(dm.resource, "getrlimit", fake_getrlimit)
        dm.check_fd_limit(stream=io.StringIO())
        assert captured["which"] == resource.RLIMIT_NOFILE


class TestMain:
    def test_returns_zero(self, monkeypatch):
        monkeypatch.setattr(dm, "check_fd_limit", lambda: True)
        assert dm.main() == 0
