"""Tests for app.py — compositor wiring and display building."""

import pytest
from rich.console import Group
from rich.text import Text


class TestBuildDisplay:
    def test_builds_group(self):
        from luna_monitor.app import build_display
        config = {
            "refresh_seconds": 2.0,
            "cache_ttl_seconds": 30,
            "drives": ["C:/"],
            "gpu_enabled": True,
            "claude_enabled": True,
        }
        result = build_display(config)
        assert isinstance(result, (Group, Text))  # Text if terminal too small

    def test_no_gpu(self):
        from luna_monitor.app import build_display
        config = {
            "refresh_seconds": 2.0,
            "cache_ttl_seconds": 30,
            "drives": ["C:/"],
            "gpu_enabled": False,
            "claude_enabled": True,
        }
        result = build_display(config)
        assert isinstance(result, (Group, Text))

    def test_no_claude(self):
        from luna_monitor.app import build_display
        config = {
            "refresh_seconds": 2.0,
            "cache_ttl_seconds": 30,
            "drives": ["C:/"],
            "gpu_enabled": True,
            "claude_enabled": False,
        }
        result = build_display(config)
        assert isinstance(result, (Group, Text))

    def test_no_gpu_no_claude(self):
        from luna_monitor.app import build_display
        config = {
            "refresh_seconds": 2.0,
            "cache_ttl_seconds": 30,
            "drives": ["C:/"],
            "gpu_enabled": False,
            "claude_enabled": False,
        }
        result = build_display(config)
        assert isinstance(result, (Group, Text))

    def test_empty_drives(self):
        from luna_monitor.app import build_display
        config = {
            "refresh_seconds": 2.0,
            "cache_ttl_seconds": 30,
            "drives": [],
            "gpu_enabled": False,
            "claude_enabled": False,
        }
        result = build_display(config)
        assert isinstance(result, (Group, Text))


class TestParseWindowNone:
    """Regression: _parse_window must handle None from API response."""

    def test_none_input(self):
        from luna_monitor.collectors.claude import _parse_window
        w = _parse_window(None)
        assert w.utilization == 0.0
        assert w.resets_at == ""
