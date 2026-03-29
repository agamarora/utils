"""Tests for luna_monitor.ui.charts — rendering utilities."""

import pytest
from collections import deque
from rich.text import Text
from rich.panel import Panel

from luna_monitor.ui.charts import (
    fmt_bytes,
    fmt_speed,
    hbar,
    wave_chart,
    make_panel,
    BLOCKS,
)


class TestFmtBytes:
    """fmt_bytes: human-readable byte formatting."""

    def test_zero(self):
        assert fmt_bytes(0) == "0.0 B"

    def test_bytes(self):
        assert fmt_bytes(512) == "512.0 B"

    def test_kilobytes(self):
        assert fmt_bytes(1024) == "1.0 KB"

    def test_megabytes(self):
        assert fmt_bytes(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        assert fmt_bytes(1024**3) == "1.0 GB"

    def test_terabytes(self):
        assert fmt_bytes(1024**4) == "1.0 TB"

    def test_petabytes(self):
        assert fmt_bytes(1024**5) == "1.0 PB"

    def test_fractional(self):
        assert fmt_bytes(1536) == "1.5 KB"

    def test_large_petabytes(self):
        # Beyond PB just keeps showing PB
        assert "PB" in fmt_bytes(1024**6)

    def test_boundary_1023(self):
        assert fmt_bytes(1023) == "1023.0 B"

    def test_boundary_1024(self):
        assert fmt_bytes(1024) == "1.0 KB"


class TestFmtSpeed:
    """fmt_speed: network speed formatting (input in Mbps)."""

    def test_zero(self):
        assert fmt_speed(0) == "0 b/s"

    def test_very_small(self):
        assert fmt_speed(0.0001) == "0 b/s"

    def test_kbps(self):
        assert fmt_speed(0.5) == "500 Kb/s"

    def test_kbps_small(self):
        assert fmt_speed(0.001) == "1 Kb/s"

    def test_mbps(self):
        assert fmt_speed(50.0) == "50.0 Mb/s"

    def test_mbps_one(self):
        assert fmt_speed(1.0) == "1.0 Mb/s"

    def test_gbps(self):
        assert fmt_speed(1000) == "1.0 Gb/s"

    def test_gbps_large(self):
        assert fmt_speed(2500) == "2.5 Gb/s"


class TestHbar:
    """hbar: horizontal percentage bar."""

    def test_zero_percent(self):
        bar = hbar(0.0, width=10)
        assert isinstance(bar, Text)
        plain = bar.plain
        assert len(plain) == 10
        assert "█" not in plain

    def test_100_percent(self):
        bar = hbar(100.0, width=10)
        plain = bar.plain
        assert plain == "█" * 10

    def test_50_percent(self):
        bar = hbar(50.0, width=20)
        plain = bar.plain
        assert len(plain) == 20
        assert plain.count("█") == 10
        assert plain.count("░") == 10

    def test_custom_width(self):
        bar = hbar(25.0, width=8)
        plain = bar.plain
        assert len(plain) == 8
        assert plain.count("█") == 2

    def test_negative_clamped(self):
        # Negative pct should produce 0 filled
        bar = hbar(-10.0, width=10)
        assert "█" not in bar.plain

    def test_over_100(self):
        # Over 100% fills completely
        bar = hbar(150.0, width=10)
        assert bar.plain.count("█") == 10


class TestWaveChart:
    """wave_chart: filled area waveform chart."""

    def test_empty_history(self):
        history = deque(maxlen=300)
        lines = wave_chart(history, console_width=80, height=5)
        assert len(lines) == 5
        for line in lines:
            assert isinstance(line, Text)

    def test_full_100_history(self):
        history = deque([100.0] * 100, maxlen=300)
        lines = wave_chart(history, console_width=80, height=5)
        # All rows should be filled blocks
        for line in lines:
            assert "█" in line.plain

    def test_full_zero_history(self):
        history = deque([0.0] * 100, maxlen=300)
        lines = wave_chart(history, console_width=80, height=5)
        # All rows should be empty
        for line in lines:
            assert line.plain.strip() == ""

    def test_height_respected(self):
        history = deque([50.0] * 10, maxlen=300)
        lines = wave_chart(history, console_width=80, height=3)
        assert len(lines) == 3

    def test_narrow_console(self):
        history = deque([50.0] * 10, maxlen=300)
        lines = wave_chart(history, console_width=24, height=3)
        assert len(lines) == 3
        # Width is max(24-4, 20) = 20
        assert len(lines[0].plain) == 20

    def test_very_narrow_console(self):
        history = deque([50.0] * 10, maxlen=300)
        lines = wave_chart(history, console_width=10, height=3)
        # Width floor is 20
        assert len(lines[0].plain) == 20

    def test_custom_style(self):
        history = deque([100.0] * 5, maxlen=300)
        lines = wave_chart(history, console_width=30, height=2, style="magenta")
        # Check that style spans contain magenta
        spans = lines[0]._spans
        assert any("magenta" in str(s.style) for s in spans)

    def test_partial_fill_uses_block_chars(self):
        # 50% should use intermediate block chars in some rows
        history = deque([50.0] * 100, maxlen=300)
        lines = wave_chart(history, console_width=80, height=7)
        all_chars = "".join(line.plain for line in lines)
        # Should have both full blocks and spaces (and possibly intermediate blocks)
        assert "█" in all_chars
        assert " " in all_chars


class TestMakePanel:
    """make_panel: Rich Panel wrapper."""

    def test_returns_panel(self):
        p = make_panel(Text("hello"), "Test")
        assert isinstance(p, Panel)

    def test_system_border(self):
        p = make_panel(Text("hello"), "System", claude=False)
        assert p.border_style == "bright_black"

    def test_claude_border(self):
        p = make_panel(Text("hello"), "Claude", claude=True)
        assert p.border_style == "cyan"

    def test_title_in_panel(self):
        p = make_panel(Text("hello"), "My Title")
        assert "My Title" in str(p.title)
