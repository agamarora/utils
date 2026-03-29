"""Tests for luna_monitor.ui.colors — color threshold functions."""

import pytest
from luna_monitor.ui.colors import pct_color, temp_color, io_color


class TestPctColor:
    """pct_color: cyan < 60 < yellow < 85 < red."""

    def test_low(self):
        assert pct_color(0.0) == "cyan"

    def test_mid_below_threshold(self):
        assert pct_color(59.9) == "cyan"

    def test_yellow_boundary(self):
        assert pct_color(60.0) == "yellow"

    def test_yellow_mid(self):
        assert pct_color(75.0) == "yellow"

    def test_yellow_upper_boundary(self):
        assert pct_color(84.9) == "yellow"

    def test_red_boundary(self):
        assert pct_color(85.0) == "red"

    def test_red_max(self):
        assert pct_color(100.0) == "red"

    def test_over_100(self):
        assert pct_color(150.0) == "red"

    def test_negative(self):
        assert pct_color(-1.0) == "cyan"


class TestTempColor:
    """temp_color: green < 70 < yellow < 85 < red."""

    def test_cool(self):
        assert temp_color(30.0) == "green"

    def test_green_upper_boundary(self):
        assert temp_color(69.9) == "green"

    def test_yellow_boundary(self):
        assert temp_color(70.0) == "yellow"

    def test_yellow_upper(self):
        assert temp_color(84.9) == "yellow"

    def test_red_boundary(self):
        assert temp_color(85.0) == "red"

    def test_red_high(self):
        assert temp_color(105.0) == "red"

    def test_zero(self):
        assert temp_color(0.0) == "green"


class TestIoColor:
    """io_color: dim < 1MB/s < cyan < 10MB/s < yellow < 100MB/s < red."""

    def test_zero(self):
        assert io_color(0.0) == "dim"

    def test_low_kbps(self):
        assert io_color(500_000) == "dim"  # 0.5 MB/s

    def test_below_1mb(self):
        assert io_color(999_999) == "dim"

    def test_1mb_boundary(self):
        assert io_color(1_000_000) == "cyan"

    def test_mid_mb(self):
        assert io_color(5_000_000) == "cyan"  # 5 MB/s

    def test_10mb_boundary(self):
        assert io_color(10_000_000) == "yellow bold"

    def test_50mb(self):
        assert io_color(50_000_000) == "yellow bold"

    def test_100mb_boundary(self):
        assert io_color(100_000_000) == "red bold"

    def test_gigabyte(self):
        assert io_color(1_000_000_000) == "red bold"
