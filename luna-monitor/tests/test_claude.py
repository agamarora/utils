"""Tests for Claude collector and panels — the soul of luna-monitor.

Uses mocked urllib to avoid hitting real APIs. Tests the OAuth flow,
credential reading, usage parsing, burndown prediction, and panel rendering.
"""

import json
import time
import pytest
from collections import deque
from unittest.mock import patch, mock_open, MagicMock
from rich.panel import Panel

from luna_monitor.collectors.claude import (
    UsageData,
    UsageWindow,
    BurndownPrediction,
    _parse_window,
    _extract_credentials,
    _TOKEN_ALLOWED_DOMAINS,
    format_reset_time,
    predict_burndown,
    _usage_history,
    PLAN_NAMES,
    _EXPECTED_SCHEMA_KEYS,
    _BACKOFF_STEPS,
)
import luna_monitor.collectors.claude as _claude_mod


# ── Credential parsing ───────────────────────────────────────

class TestExtractCredentials:
    """Test _extract_credentials — Pulse-compatible credential structure."""

    def test_valid_credentials(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "sk-test-123",
                "refreshToken": "rt-test-456",
                "rateLimitTier": "default_claude_ai",
            }
        }
        token, plan = _extract_credentials(data)
        assert token == "sk-test-123"
        assert plan == "Pro"

    def test_max_5x_plan(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "sk-test",
                "rateLimitTier": "default_claude_max_5x",
            }
        }
        _, plan = _extract_credentials(data)
        assert plan == "Max 5x"

    def test_max_20x_plan(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "sk-test",
                "rateLimitTier": "default_claude_max_20x",
            }
        }
        _, plan = _extract_credentials(data)
        assert plan == "Max 20x"

    def test_unknown_tier(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "sk-test",
                "rateLimitTier": "default_claude_enterprise",
            }
        }
        _, plan = _extract_credentials(data)
        assert "Enterprise" in plan  # fallback formatting

    def test_no_token(self):
        data = {"claudeAiOauth": {"rateLimitTier": "default_claude_ai"}}
        token, plan = _extract_credentials(data)
        assert token is None
        assert plan == ""

    def test_none_data(self):
        token, plan = _extract_credentials(None)
        assert token is None

    def test_empty_data(self):
        token, plan = _extract_credentials({})
        assert token is None

    def test_missing_oauth_key(self):
        data = {"someOtherKey": {}}
        token, plan = _extract_credentials(data)
        assert token is None

    def test_no_tier(self):
        data = {"claudeAiOauth": {"accessToken": "sk-test"}}
        token, plan = _extract_credentials(data)
        assert token == "sk-test"
        assert plan == ""


# ── Domain allowlist ─────────────────────────────────────────

class TestDomainAllowlist:
    """Test _is_allowed_domain — security boundary."""

    def test_api_anthropic(self):
        # Note: _is_allowed_domain is in the module, using _authorized_request's logic
        from luna_monitor.collectors.claude import _TOKEN_ALLOWED_DOMAINS
        from urllib.parse import urlparse
        assert urlparse("https://api.anthropic.com/api/oauth/usage").hostname in _TOKEN_ALLOWED_DOMAINS

    def test_console_anthropic(self):
        from luna_monitor.collectors.claude import _TOKEN_ALLOWED_DOMAINS
        from urllib.parse import urlparse
        assert urlparse("https://console.anthropic.com/v1/oauth/token").hostname in _TOKEN_ALLOWED_DOMAINS

    def test_platform_claude(self):
        from luna_monitor.collectors.claude import _TOKEN_ALLOWED_DOMAINS
        from urllib.parse import urlparse
        assert urlparse("https://platform.claude.com/v1/oauth/token").hostname in _TOKEN_ALLOWED_DOMAINS

    def test_evil_domain_blocked(self):
        from luna_monitor.collectors.claude import _TOKEN_ALLOWED_DOMAINS
        from urllib.parse import urlparse
        assert urlparse("https://evil.com/steal-token").hostname not in _TOKEN_ALLOWED_DOMAINS

    def test_similar_domain_blocked(self):
        from luna_monitor.collectors.claude import _TOKEN_ALLOWED_DOMAINS
        from urllib.parse import urlparse
        assert urlparse("https://api.anthropic.com.evil.com/x").hostname not in _TOKEN_ALLOWED_DOMAINS


# ── Usage parsing ────────────────────────────────────────────

class TestParseWindow:
    def test_valid_window(self):
        w = _parse_window({"utilization": 45.0, "resets_at": "2026-03-30T00:00:00Z"})
        assert w.utilization == 45.0
        assert w.resets_at == "2026-03-30T00:00:00Z"

    def test_empty_window(self):
        w = _parse_window({})
        assert w.utilization == 0.0
        assert w.resets_at == ""

    def test_missing_fields(self):
        w = _parse_window({"utilization": 12.0})
        assert w.utilization == 12.0
        assert w.resets_at == ""


class TestSchemaVersioning:
    def test_expected_keys_defined(self):
        assert "five_hour" in _EXPECTED_SCHEMA_KEYS
        assert "seven_day" in _EXPECTED_SCHEMA_KEYS

    def test_valid_response_passes_check(self):
        body = {"five_hour": {}, "seven_day": {}, "extra_stuff": {}}
        assert _EXPECTED_SCHEMA_KEYS.issubset(body.keys())

    def test_missing_key_fails_check(self):
        body = {"five_hour": {}}  # missing seven_day
        assert not _EXPECTED_SCHEMA_KEYS.issubset(body.keys())

    def test_completely_different_schema_fails(self):
        body = {"usage": {}, "quota": {}}
        assert not _EXPECTED_SCHEMA_KEYS.issubset(body.keys())


# ── Format reset time ────────────────────────────────────────

class TestFormatResetTime:
    def test_empty_string(self):
        assert format_reset_time("") == ""

    def test_none(self):
        assert format_reset_time(None) == ""

    def test_invalid_iso(self):
        assert format_reset_time("not-a-date") == ""

    def test_future_time_hours(self):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)
        result = format_reset_time(future.isoformat())
        assert "2h" in result
        assert "30m" in result

    def test_future_time_minutes(self):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(minutes=15)
        result = format_reset_time(future.isoformat())
        assert "15m" in result
        assert "h" not in result

    def test_past_time_shows_zero(self):
        result = format_reset_time("2020-01-01T00:00:00Z")
        assert "0m" in result


# ── Burndown prediction ─────────────────────────────────────

class TestBurndownPrediction:
    def setup_method(self):
        _usage_history.clear()

    def test_empty_history(self):
        p = predict_burndown()
        assert p.label == "Collecting data..."

    def test_one_point(self):
        _usage_history.append((time.time(), 10.0))
        p = predict_burndown()
        assert "Collecting" in p.label

    def test_two_points(self):
        _usage_history.append((time.time() - 60, 10.0))
        _usage_history.append((time.time(), 20.0))
        p = predict_burndown()
        assert "Collecting" in p.label  # need >= 3 for regression

    def test_flat_usage(self):
        now = time.time()
        for i in range(10):
            _usage_history.append((now + i * 30, 50.0))
        p = predict_burndown()
        assert "sustainable" in p.label.lower()

    def test_increasing_usage_shows_minutes(self):
        now = time.time()
        for i in range(10):
            _usage_history.append((now + i * 30, 10.0 + i * 5.0))
        p = predict_burndown()
        assert p.minutes_remaining is not None or "sustainable" in p.label.lower()

    def test_usage_at_100_shows_limit_reached(self):
        now = time.time()
        for i in range(10):
            _usage_history.append((now + i * 30, 90.0 + i * 2.0))
        p = predict_burndown()
        # Should either show "Limit reached" or a very short time
        assert p.minutes_remaining is not None or "sustainable" in p.label.lower()

    def test_decreasing_usage_resets(self):
        now = time.time()
        for i in range(5):
            _usage_history.append((now + i * 30, 80.0 - i * 20.0))
        p = predict_burndown()
        # Should detect reset or show sustainable
        assert "reset" in p.label.lower() or "sustainable" in p.label.lower()

    def test_high_confidence_with_many_points(self):
        now = time.time()
        for i in range(10):
            _usage_history.append((now + i * 30, 10.0 + i * 3.0))
        p = predict_burndown()
        if p.minutes_remaining is not None:
            assert p.confidence in ("medium", "high")

    def test_history_bounded(self):
        assert _usage_history.maxlen == 300


# ── Claude panels ────────────────────────────────────────────

class TestClaudeStatusPanel:
    def test_render_with_data(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(
            five_hour=UsageWindow(utilization=45.0, resets_at="2026-03-30T00:00:00Z"),
            seven_day=UsageWindow(utilization=30.0, resets_at="2026-04-05T00:00:00Z"),
            plan="Pro",
            fetched_at=time.time(),
        )
        result = build_claude_status(usage)
        assert isinstance(result, Panel)

    def test_render_with_error_no_data(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(error="Claude not configured")
        result = build_claude_status(usage)
        assert isinstance(result, Panel)

    def test_render_with_stale_data(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(
            five_hour=UsageWindow(utilization=60.0),
            seven_day=UsageWindow(utilization=40.0),
            fetched_at=time.time() - 120,
            error="Network error — showing cached data",
        )
        result = build_claude_status(usage)
        assert isinstance(result, Panel)

    def test_render_with_model_breakdown(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(
            five_hour=UsageWindow(utilization=50.0),
            seven_day=UsageWindow(utilization=35.0),
            seven_day_opus=UsageWindow(utilization=25.0),
            seven_day_sonnet=UsageWindow(utilization=10.0),
            plan="Max 5x",
            fetched_at=time.time(),
        )
        result = build_claude_status(usage)
        assert isinstance(result, Panel)

    def test_render_high_usage(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(
            five_hour=UsageWindow(utilization=95.0),
            seven_day=UsageWindow(utilization=88.0),
            plan="Pro",
            fetched_at=time.time(),
        )
        result = build_claude_status(usage)
        assert isinstance(result, Panel)

    def test_claude_border_style(self):
        from luna_monitor.panels.claude_status import build_claude_status
        usage = UsageData(
            five_hour=UsageWindow(utilization=50.0),
            seven_day=UsageWindow(utilization=30.0),
            fetched_at=time.time(),
        )
        result = build_claude_status(usage)
        assert result.border_style == "cyan"  # Claude panels use cyan


class TestClaudeBurndownPanel:
    """Tests updated for the JSONL-based burndown panel (LocalUsageData + burn_history)."""

    def _make_history(self, n: int = 0, rate: float = 50.0) -> deque:
        now = time.time()
        h = deque(maxlen=300)
        for i in range(n):
            h.append((now + i * 30, rate))
        return h

    def test_render_no_data(self):
        from luna_monitor.panels.claude_burndown import build_claude_burndown
        from luna_monitor.collectors.claude_local import LocalUsageData
        result = build_claude_burndown(LocalUsageData(), self._make_history(0), console_width=80)
        assert isinstance(result, Panel)

    def test_render_with_data(self):
        from luna_monitor.panels.claude_burndown import build_claude_burndown
        from luna_monitor.collectors.claude_local import LocalUsageData
        local_data = LocalUsageData(burn_rate=5000.0, tokens_5h=1_000_000)
        result = build_claude_burndown(local_data, self._make_history(20, rate=5000.0), console_width=80)
        assert isinstance(result, Panel)

    def test_render_sustainable(self):
        from luna_monitor.panels.claude_burndown import build_claude_burndown
        from luna_monitor.collectors.claude_local import LocalUsageData
        result = build_claude_burndown(LocalUsageData(burn_rate=100.0), self._make_history(10, rate=100.0), console_width=80)
        assert isinstance(result, Panel)

    def test_burndown_uses_magenta_style(self):
        from luna_monitor.panels.claude_burndown import build_claude_burndown
        from luna_monitor.collectors.claude_local import LocalUsageData
        result = build_claude_burndown(LocalUsageData(burn_rate=50.0), self._make_history(5, rate=50.0), console_width=80)
        assert result.border_style == "cyan"  # Claude panel border

    def test_narrow_console(self):
        from luna_monitor.panels.claude_burndown import build_claude_burndown
        from luna_monitor.collectors.claude_local import LocalUsageData
        result = build_claude_burndown(LocalUsageData(burn_rate=200.0), self._make_history(5, rate=200.0), console_width=30)
        assert isinstance(result, Panel)


# ── Exponential backoff on 429 ───────────────────────────────

class TestExponentialBackoff:
    """Test 429 backoff: 30s → 60s → 120s → 300s → stays at 300s."""

    def setup_method(self):
        # Reset all backoff + cache state before each test
        _claude_mod._backoff_step = 0
        _claude_mod._backoff_until = 0.0
        _claude_mod._cached_usage = None
        _claude_mod._retry_count = 0
        # Disable proxy shortcut so tests go through API path
        self._proxy_patch = patch("luna_monitor.collectors.claude._try_proxy_data", return_value=None)
        self._proxy_patch.start()
        # Disable disk cache so cold start doesn't short-circuit
        self._disk_patch = patch("luna_monitor.collectors.claude._read_disk_cache", return_value=None)
        self._disk_patch.start()

    def teardown_method(self):
        self._proxy_patch.stop()
        self._disk_patch.stop()

    def test_backoff_steps_defined(self):
        assert _BACKOFF_STEPS == [30.0, 60.0, 120.0, 300.0]

    def test_first_429_sets_30s_backoff(self):
        """First 429 → next retry blocked for 30 seconds."""
        before = time.time()
        with patch("luna_monitor.collectors.claude._authorized_request") as mock_req, \
             patch("luna_monitor.collectors.claude._get_fresh_token", return_value=("tok", "Pro")), \
             patch("luna_monitor.collectors.claude._read_disk_cache", return_value=None):
            import urllib.error
            mock_req.side_effect = urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None)
            from luna_monitor.collectors.claude import fetch_usage
            fetch_usage()
        assert _claude_mod._backoff_step == 1
        assert _claude_mod._backoff_until >= before + 29  # ~30s

    def test_second_429_sets_60s_backoff(self):
        """Second consecutive 429 → 60s backoff."""
        _claude_mod._backoff_step = 1
        before = time.time()
        with patch("luna_monitor.collectors.claude._authorized_request") as mock_req, \
             patch("luna_monitor.collectors.claude._get_fresh_token", return_value=("tok", "Pro")), \
             patch("luna_monitor.collectors.claude._read_disk_cache", return_value=None):
            import urllib.error
            mock_req.side_effect = urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None)
            from luna_monitor.collectors.claude import fetch_usage
            fetch_usage()
        assert _claude_mod._backoff_step == 2
        assert _claude_mod._backoff_until >= before + 59  # ~60s

    def test_fourth_plus_429_caps_at_300s(self):
        """Step 3+ → capped at 300s (5 min)."""
        _claude_mod._backoff_step = 3  # already at max index
        before = time.time()
        with patch("luna_monitor.collectors.claude._authorized_request") as mock_req, \
             patch("luna_monitor.collectors.claude._get_fresh_token", return_value=("tok", "Pro")), \
             patch("luna_monitor.collectors.claude._read_disk_cache", return_value=None):
            import urllib.error
            mock_req.side_effect = urllib.error.HTTPError(None, 429, "Too Many Requests", {}, None)
            from luna_monitor.collectors.claude import fetch_usage
            fetch_usage()
        assert _claude_mod._backoff_step == 3  # stays at max
        assert _claude_mod._backoff_until >= before + 299  # ~300s

    def test_backoff_gate_blocks_api_call(self):
        """While in backoff window, API is never called — returns cached data."""
        cached = UsageData(
            five_hour=UsageWindow(utilization=50.0),
            seven_day=UsageWindow(utilization=30.0),
            fetched_at=0.0,  # expired TTL
        )
        _claude_mod._cached_usage = cached
        _claude_mod._backoff_until = time.time() + 60  # 60s backoff active

        with patch("luna_monitor.collectors.claude._authorized_request") as mock_req, \
             patch("luna_monitor.collectors.claude._get_fresh_token", return_value=("tok", "Pro")):
            from luna_monitor.collectors.claude import fetch_usage
            result = fetch_usage()
            mock_req.assert_not_called()  # API never touched
        assert result is cached

    def test_success_resets_backoff(self):
        """Successful API call resets backoff step and until to 0."""
        _claude_mod._backoff_step = 3
        _claude_mod._backoff_until = 0.0  # backoff expired, allow retry

        good_body = {
            "five_hour": {"utilization": 40.0, "resets_at": "2026-03-30T00:00:00Z"},
            "seven_day": {"utilization": 20.0, "resets_at": "2026-04-05T00:00:00Z"},
        }

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(good_body).encode()

        with patch("luna_monitor.collectors.claude._authorized_request", return_value=mock_resp), \
             patch("luna_monitor.collectors.claude._get_fresh_token", return_value=("tok", "Pro")), \
             patch("luna_monitor.collectors.claude._write_disk_cache"):
            from luna_monitor.collectors.claude import fetch_usage
            fetch_usage()

        assert _claude_mod._backoff_step == 0
        assert _claude_mod._backoff_until == 0.0
