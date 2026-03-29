"""Tests for collectors/rate_limit.py — proxy-captured rate limit data."""

import json
import time
from unittest.mock import patch

import pytest

from luna_monitor.collectors import rate_limit
from luna_monitor.collectors.rate_limit import (
    RateLimitData,
    collect,
    freshness,
    _read_latest,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset module-level cache between tests."""
    rate_limit._cached = None
    rate_limit._cached_at = 0.0
    yield


# ── Happy path ───────────────────────────────────────────────

def test_read_jsonl_happy_path(tmp_path):
    """Valid JSONL file returns RateLimitData with correct values."""
    jf = tmp_path / "rate-limits.jsonl"
    entry = {
        "ts": "2026-03-29T17:30:00Z",
        "5h_utilization": 0.42,
        "7d_utilization": 0.15,
        "5h_reset": "2026-03-29T22:30:00Z",
        "7d_reset": "2026-04-05T00:00:00Z",
        "status": "ok",
    }
    jf.write_text(json.dumps(entry) + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)

    assert result is not None
    assert result.util_5h == 0.42
    assert result.util_7d == 0.15
    assert result.reset_5h == "2026-03-29T22:30:00Z"
    assert result.reset_7d == "2026-04-05T00:00:00Z"
    assert result.status == "ok"
    assert result.captured_at == "2026-03-29T17:30:00Z"


def test_read_latest_multiple_entries(tmp_path):
    """Returns the last valid entry when multiple exist."""
    jf = tmp_path / "rate-limits.jsonl"
    old = json.dumps({"ts": "2026-03-29T10:00:00Z", "5h_utilization": 0.10})
    new = json.dumps({"ts": "2026-03-29T17:00:00Z", "5h_utilization": 0.55})
    jf.write_text(old + "\n" + new + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = _read_latest()

    assert result is not None
    assert result.util_5h == 0.55


# ── Cache ────────────────────────────────────────────────────

def test_cache_ttl(tmp_path):
    """Second call within TTL returns cached result without re-reading file."""
    jf = tmp_path / "rate-limits.jsonl"
    entry = json.dumps({"ts": "2026-03-29T17:30:00Z", "5h_utilization": 0.42})
    jf.write_text(entry + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        first = collect(cache_ttl=10)
        # Delete file — should still return cached
        jf.unlink()
        second = collect(cache_ttl=10)

    assert first is second  # same object (cached)


def test_cache_expired(tmp_path):
    """After TTL expires, re-reads from file."""
    jf = tmp_path / "rate-limits.jsonl"
    entry = json.dumps({"ts": "2026-03-29T17:30:00Z", "5h_utilization": 0.42})
    jf.write_text(entry + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        first = collect(cache_ttl=0)  # ttl=0 forces re-read
        # Update file
        new_entry = json.dumps({"ts": "2026-03-29T18:00:00Z", "5h_utilization": 0.99})
        jf.write_text(new_entry + "\n")
        second = collect(cache_ttl=0)

    assert second is not None
    assert second.util_5h == 0.99


# ── Missing/empty file ──────────────────────────────────────

def test_missing_file():
    """Returns None when file doesn't exist."""
    with patch.object(rate_limit, "_RATE_LIMIT_FILE", "/nonexistent/path.jsonl"):
        result = collect(cache_ttl=0)
    assert result is None


def test_empty_file(tmp_path):
    """Returns None when file is empty."""
    jf = tmp_path / "rate-limits.jsonl"
    jf.write_text("")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)
    assert result is None


# ── Malformed entries ────────────────────────────────────────

def test_malformed_last_line(tmp_path):
    """Falls back to previous valid entry when last line is corrupted."""
    jf = tmp_path / "rate-limits.jsonl"
    good = json.dumps({"ts": "2026-03-29T17:00:00Z", "5h_utilization": 0.30})
    jf.write_text(good + "\n" + "CORRUPTED{not json\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)

    assert result is not None
    assert result.util_5h == 0.30


def test_all_malformed(tmp_path):
    """Returns None when all entries are malformed."""
    jf = tmp_path / "rate-limits.jsonl"
    jf.write_text("bad1\nbad2\n{not json\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)
    assert result is None


# ── Freshness ────────────────────────────────────────────────

def test_freshness_fresh():
    """Data captured just now is fresh."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = RateLimitData(captured_at=now)
    assert freshness(data, max_age_s=60.0) is True


def test_freshness_stale():
    """Data captured 2 minutes ago is stale with 60s threshold."""
    data = RateLimitData(captured_at="2020-01-01T00:00:00Z")
    assert freshness(data, max_age_s=60.0) is False


def test_freshness_none():
    """None data is not fresh."""
    assert freshness(None) is False


def test_freshness_empty_timestamp():
    """Empty timestamp is not fresh."""
    data = RateLimitData(captured_at="")
    assert freshness(data) is False


# ── Edge cases ───────────────────────────────────────────────

def test_missing_fields(tmp_path):
    """Missing fields default to 0.0 or empty string."""
    jf = tmp_path / "rate-limits.jsonl"
    entry = json.dumps({"ts": "2026-03-29T17:30:00Z"})
    jf.write_text(entry + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)

    assert result is not None
    assert result.util_5h == 0.0
    assert result.util_7d == 0.0
    assert result.reset_5h == ""


def test_non_numeric_utilization(tmp_path):
    """Non-numeric utilization defaults to 0.0."""
    jf = tmp_path / "rate-limits.jsonl"
    entry = json.dumps({"ts": "2026-03-29T17:30:00Z", "5h_utilization": "bad"})
    jf.write_text(entry + "\n")

    with patch.object(rate_limit, "_RATE_LIMIT_FILE", str(jf)):
        result = collect(cache_ttl=0)

    assert result is not None
    assert result.util_5h == 0.0
