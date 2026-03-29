"""Tests for proxy/watchdog.py — health monitoring and auto-restart."""

import time
from unittest.mock import patch, call

import pytest

from luna_monitor.proxy import watchdog


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset watchdog state between tests."""
    watchdog.consecutive_failures = 0
    watchdog.is_recovering = False
    watchdog.last_check_time = 0.0
    yield
    watchdog.stop_watchdog()


def test_healthy_proxy_resets_failures():
    """Consecutive failures reset to 0 when proxy is healthy."""
    watchdog.consecutive_failures = 2

    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=True), \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.1):
        t = watchdog.start_watchdog()
        time.sleep(0.3)
        watchdog.stop_watchdog()

    assert watchdog.consecutive_failures == 0
    assert watchdog.is_recovering is False


def test_failure_increments_counter():
    """Each health check failure increments the counter."""
    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=False), \
         patch("luna_monitor.proxy.watchdog.restart_proxy", return_value=False), \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.05):
        t = watchdog.start_watchdog()
        time.sleep(0.2)
        watchdog.stop_watchdog()

    assert watchdog.consecutive_failures > 0


def test_three_failures_sets_recovering():
    """After 3 consecutive failures, is_recovering is set."""
    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=False), \
         patch("luna_monitor.proxy.watchdog.restart_proxy", return_value=False), \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.05), \
         patch("luna_monitor.proxy.watchdog._FAILURE_THRESHOLD", 3):
        t = watchdog.start_watchdog()
        time.sleep(0.3)
        watchdog.stop_watchdog()

    assert watchdog.is_recovering is True


def test_restart_on_failure():
    """Watchdog calls restart_proxy on each failure."""
    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=False), \
         patch("luna_monitor.proxy.watchdog.restart_proxy", return_value=False) as mock_restart, \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.05):
        t = watchdog.start_watchdog()
        time.sleep(0.2)
        watchdog.stop_watchdog()

    assert mock_restart.call_count > 0


def test_successful_restart_resets_state():
    """Successful restart resets failures and recovery flag."""
    watchdog.consecutive_failures = 5
    watchdog.is_recovering = True

    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=False), \
         patch("luna_monitor.proxy.watchdog.restart_proxy", return_value=True), \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.05):
        t = watchdog.start_watchdog()
        time.sleep(0.15)
        watchdog.stop_watchdog()

    assert watchdog.consecutive_failures == 0
    assert watchdog.is_recovering is False


def test_stop_watchdog():
    """Watchdog thread stops cleanly."""
    with patch("luna_monitor.proxy.watchdog.is_proxy_healthy", return_value=True), \
         patch("luna_monitor.proxy.watchdog._CHECK_INTERVAL", 0.05):
        t = watchdog.start_watchdog()
        assert t.is_alive()
        watchdog.stop_watchdog()
        time.sleep(0.15)
        assert not t.is_alive()
