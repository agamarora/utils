"""Rate limit data collector — reads proxy-captured headers from JSONL.

Reads ~/.luna-monitor/rate-limits.jsonl (written by luna-proxy) and returns
the most recent rate limit entry. Uses a 2s cache to match the refresh loop.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

# ── Constants ────────────────────────────────────────────────

_RATE_LIMIT_FILE = str(Path.home() / ".luna-monitor" / "rate-limits.jsonl")
_CACHE_TTL: float = 2.0


# ── Data types ───────────────────────────────────────────────

@dataclass
class RateLimitData:
    """Rate limit data captured by the proxy."""
    util_5h: float = 0.0        # 0.0 to 1.0 (raw from header)
    util_7d: float = 0.0        # 0.0 to 1.0 (raw from header)
    reset_5h: str = ""          # ISO 8601 timestamp
    reset_7d: str = ""          # ISO 8601 timestamp
    status: str = ""            # e.g., "ok"
    captured_at: str = ""       # ISO 8601 timestamp from proxy


# ── Module state ─────────────────────────────────────────────

_cached: RateLimitData | None = None
_cached_at: float = 0.0


# ── Public API ───────────────────────────────────────────────

def collect(cache_ttl: float = _CACHE_TTL) -> RateLimitData | None:
    """Read the most recent rate limit entry from the proxy JSONL file.

    Returns None if file doesn't exist, is empty, or has no valid entries.
    Caches result for cache_ttl seconds.
    """
    global _cached, _cached_at

    now = time.time()
    if _cached is not None and (now - _cached_at) < cache_ttl:
        return _cached

    result = _read_latest()
    _cached = result
    _cached_at = now
    return result


def freshness(data: RateLimitData | None, max_age_s: float = 60.0) -> bool:
    """Check if rate limit data is fresh enough to use (default: within 60s)."""
    if data is None or not data.captured_at:
        return False
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(data.captured_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age < max_age_s
    except (ValueError, TypeError):
        return False


# ── Internal ─────────────────────────────────────────────────

def _read_latest() -> RateLimitData | None:
    """Read the last valid entry from the JSONL file. Never raises."""
    try:
        with open(_RATE_LIMIT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    # Walk backwards to find the last valid entry
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        return RateLimitData(
            util_5h=_to_float(entry.get("5h_utilization", 0.0)),
            util_7d=_to_float(entry.get("7d_utilization", 0.0)),
            reset_5h=str(entry.get("5h_reset", "")),
            reset_7d=str(entry.get("7d_reset", "")),
            status=str(entry.get("status", "")),
            captured_at=str(entry.get("ts", "")),
        )

    return None


def _to_float(val) -> float:
    """Convert to float, defaulting to 0.0."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ── Proxy health / API stats ────────────────────────────────

@dataclass
class ProxyHealth:
    """Health and API stats from the proxy's /health endpoint."""
    proxy_up: bool = False
    uptime_s: int = 0
    requests_proxied: int = 0
    api_errors_total: int = 0
    api_errors_429: int = 0
    last_latency_ms: float = 0.0


_health_cached: ProxyHealth | None = None
_health_cached_at: float = 0.0


def collect_proxy_health(port: int = 9120, cache_ttl: float = _CACHE_TTL) -> ProxyHealth:
    """Fetch proxy health and API stats. Returns ProxyHealth (proxy_up=False if down)."""
    global _health_cached, _health_cached_at

    now = time.time()
    if _health_cached is not None and (now - _health_cached_at) < cache_ttl:
        return _health_cached

    result = _fetch_health(port)
    _health_cached = result
    _health_cached_at = now
    return result


def _fetch_health(port: int) -> ProxyHealth:
    """GET /health from the proxy. Never raises."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=1
        ) as resp:
            if resp.status != 200:
                return ProxyHealth()
            data = json.loads(resp.read(10_000))
            return ProxyHealth(
                proxy_up=True,
                uptime_s=int(data.get("uptime_s", 0)),
                requests_proxied=int(data.get("requests_proxied", 0)),
                api_errors_total=int(data.get("api_errors_total", 0)),
                api_errors_429=int(data.get("api_errors_429", 0)),
                last_latency_ms=_to_float(data.get("last_latency_ms", 0)),
            )
    except Exception:
        return ProxyHealth()
