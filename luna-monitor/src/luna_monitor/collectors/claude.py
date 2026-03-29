"""Claude Code usage collector — OAuth token management + Anthropic usage API.

Modeled after Claude Pulse (claude_status.py) which is the most reliable
implementation of this flow. Key patterns borrowed from Pulse:
- Credential structure: data["claudeAiOauth"]["accessToken"] (nested)
- Refresh URL: https://platform.claude.com/v1/oauth/token
- No-redirect handler to prevent token exfiltration
- Domain allowlist: api.anthropic.com, console.anthropic.com, platform.claude.com
- macOS Keychain fallback for credentials
- Refresh request sends NO Bearer header (only refresh_token in body)
- Never writes tokens to disk

SECURITY: Tokens stored in-memory only. Domain allowlist hardcoded.
Never log or display token values.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ── Constants ────────────────────────────────────────────────

CREDENTIALS_PATH = str(Path.home() / ".claude" / ".credentials.json")

# Hardcoded domain allowlist — tokens are ONLY sent to these domains
_TOKEN_ALLOWED_DOMAINS = frozenset({
    "api.anthropic.com",
    "console.anthropic.com",
    "platform.claude.com",
})

_TOKEN_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
_USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
_USAGE_API_BETA = "oauth-2025-04-20"

# Expected top-level keys in usage API response — for schema versioning
_EXPECTED_SCHEMA_KEYS = {"five_hour", "seven_day"}

PLAN_NAMES = {
    "default_claude_ai": "Pro",
    "default_claude_max_5x": "Max 5x",
    "default_claude_max_20x": "Max 20x",
}


# ── Security: redirect blocking ─────────────────────────────

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block HTTP redirects to prevent tokens from leaking to third-party domains."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target_domain = urlparse(newurl).hostname
        if target_domain not in _TOKEN_ALLOWED_DOMAINS:
            raise urllib.error.HTTPError(
                newurl, code, "Redirect to non-allowed domain blocked", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(_NoRedirectHandler)


def _authorized_request(url, token, headers=None, data=None, method=None, timeout=10):
    """Make an HTTP request, only to allowed Anthropic domains.

    Raises ValueError if domain not in allowlist.
    Uses redirect-blocking opener to prevent token exfiltration.
    """
    domain = urlparse(url).hostname
    if domain not in _TOKEN_ALLOWED_DOMAINS:
        raise ValueError(f"Token request blocked: {domain} is not an allowed domain")
    hdrs = dict(headers) if headers else {}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.setdefault("User-Agent", "luna-monitor/0.1.0")
    req = urllib.request.Request(url, headers=hdrs, data=data, method=method)
    return _safe_opener.open(req, timeout=timeout)


# ── Data types ───────────────────────────────────────────────

@dataclass
class UsageWindow:
    """A single usage window (e.g., five_hour, seven_day)."""
    utilization: float = 0.0  # 0.0 to 1.0
    resets_at: str = ""       # ISO 8601 timestamp


@dataclass
class UsageData:
    """All usage data from the Anthropic API."""
    five_hour: UsageWindow = field(default_factory=UsageWindow)
    seven_day: UsageWindow = field(default_factory=UsageWindow)
    seven_day_opus: UsageWindow = field(default_factory=UsageWindow)
    seven_day_sonnet: UsageWindow = field(default_factory=UsageWindow)
    extra_usage: dict = field(default_factory=dict)
    plan: str = ""            # "Pro", "Max 5x", "Max 20x"
    fetched_at: float = 0.0
    error: str = ""           # non-empty if there was a problem


@dataclass
class BurndownPrediction:
    """Burndown prediction result."""
    minutes_remaining: float | None = None  # None if can't predict
    label: str = "Collecting data..."       # human-readable label
    confidence: str = "low"                 # low, medium, high


# ── State ────────────────────────────────────────────────────

_access_token: str | None = None
_plan: str = ""

_cached_usage: UsageData | None = None
_cache_ttl: float = 30.0  # seconds

_usage_history: deque = deque(maxlen=300)  # (timestamp, utilization) pairs

# Credential file cache — avoid reading disk every 2 seconds
_cred_cache: tuple[dict | None, str | None] | None = None
_cred_cache_time: float = 0.0
_CRED_CACHE_TTL: float = 30.0  # re-read credentials file every 30s

# Exponential backoff on 429 — 30s → 60s → 120s → 300s, then stays at 5 min
_BACKOFF_STEPS: list[float] = [30.0, 60.0, 120.0, 300.0]
_backoff_step: int = 0    # index into _BACKOFF_STEPS
_backoff_until: float = 0.0  # epoch timestamp — no API calls before this

# Disk-based cache — survives restarts, used on 429 and cold start
_DISK_CACHE_DIR = str(Path.home() / ".luna-monitor")
_DISK_CACHE_FILE = str(Path.home() / ".luna-monitor" / "usage-cache.json")
_USAGE_CACHE_KEYS = {"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "extra_usage"}


# ── Credential reading (matches Pulse's structure) ───────────

def _read_credential_data() -> tuple[dict | None, str | None]:
    """Read raw credential data from file or macOS Keychain. Returns (dict, source).

    Caches the result for _CRED_CACHE_TTL seconds to avoid disk I/O every 2s refresh.
    """
    global _cred_cache, _cred_cache_time
    now = time.time()
    if _cred_cache is not None and (now - _cred_cache_time) < _CRED_CACHE_TTL:
        return _cred_cache

    result = _read_credential_data_uncached()
    _cred_cache = result
    _cred_cache_time = now
    return result


def _read_credential_data_uncached() -> tuple[dict | None, str | None]:
    """Actually read credentials from disk/keychain (no cache)."""
    # 1. File-based (~/.claude/.credentials.json)
    try:
        with open(CREDENTIALS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("claudeAiOauth", {}).get("accessToken"):
            return data, "file"
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # 2. macOS Keychain fallback
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password",
                 "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                if data.get("claudeAiOauth", {}).get("accessToken"):
                    return data, "keychain"
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, ValueError):
            pass

    return None, None


def _extract_credentials(data: dict | None) -> tuple[str | None, str]:
    """Extract token and plan name from credential data dict."""
    if not data:
        return None, ""
    oauth = data.get("claudeAiOauth", {})
    token = oauth.get("accessToken")
    tier = oauth.get("rateLimitTier", "")
    if not token:
        return None, ""
    plan = PLAN_NAMES.get(
        tier,
        tier.replace("default_claude_", "").replace("_", " ").title() if tier else "",
    )
    return token, plan


def _refresh_oauth_token(refresh_token: str) -> dict | None:
    """Use refresh token to get a new access token. Returns token data or None.

    Sends NO Bearer header — only the refresh_token in the request body.
    """
    try:
        body = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode("utf-8")
        with _authorized_request(
            _TOKEN_REFRESH_URL,
            None,  # no Bearer token for refresh
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        ) as resp:
            return json.loads(resp.read(100_000))
    except Exception:
        return None


def get_credentials() -> tuple[str | None, str]:
    """Read OAuth token from credentials. Returns (token, plan_name)."""
    global _access_token, _plan

    # Try environment variable first
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env_token:
        _access_token = env_token
        _plan = ""
        return env_token, ""

    data, source = _read_credential_data()
    if data:
        token, plan = _extract_credentials(data)
        if token:
            _access_token = token
            _plan = plan
            return token, plan

    return None, ""


def refresh_and_retry() -> tuple[str | None, str]:
    """Attempt to refresh expired OAuth token. Returns (new_token, plan) or (None, plan)."""
    global _access_token
    data, source = _read_credential_data()
    if not data:
        return None, _plan
    oauth = data.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        return None, _plan

    token_data = _refresh_oauth_token(refresh_token)
    if not token_data or "access_token" not in token_data:
        return None, _plan

    # Store in-memory only — never write back to credential file
    _access_token = token_data["access_token"]
    return _access_token, _plan


def _get_fresh_token() -> tuple[str | None, str]:
    """Read token fresh from credentials file every time (like Pulse does).

    Claude Code manages the credentials file and keeps it updated.
    We piggyback on that rather than caching tokens in memory.
    """
    global _access_token, _plan
    token, plan = get_credentials()
    if token:
        _access_token = token
        _plan = plan
    return token, plan


# ── Usage API ────────────────────────────────────────────────

def _try_proxy_data() -> UsageData | None:
    """Check if luna-proxy has fresh rate limit data. Returns UsageData or None.

    If the proxy is running and has captured headers within the last 60 seconds,
    build a UsageData from the proxy data instead of calling the broken usage API.
    """
    try:
        from luna_monitor.collectors.rate_limit import collect as rl_collect, freshness
        rl_data = rl_collect()
        if rl_data is None or not freshness(rl_data, max_age_s=60.0):
            return None

        # Proxy headers report utilization as 0.0-1.0, we store as 0-100
        usage = UsageData(
            five_hour=UsageWindow(
                utilization=max(0.0, min(100.0, rl_data.util_5h * 100.0)),
                resets_at=rl_data.reset_5h,
            ),
            seven_day=UsageWindow(
                utilization=max(0.0, min(100.0, rl_data.util_7d * 100.0)),
                resets_at=rl_data.reset_7d,
            ),
            plan=_plan,
            fetched_at=time.time(),
            error="",
        )

        # Track utilization history for burndown
        _usage_history.append((time.time(), usage.five_hour.utilization))

        # Mark source so the UI can indicate "via proxy"
        usage.extra_usage = {"_source": "proxy"}

        return usage
    except Exception:
        return None


_retry_count = 0  # prevent infinite retry loops

def fetch_usage(cache_ttl: float | None = None) -> UsageData:
    """Fetch Claude usage data from the Anthropic API or proxy.

    Reads token fresh from credentials file every call (same as Pulse).
    Returns cached data if within TTL. On error, returns last cached data
    with an error message, or a fresh UsageData with error set.

    If luna-proxy is running, uses proxy-captured rate limit headers instead
    of the (broken) usage API. Falls back to API if proxy data is stale.

    Uses exponential backoff on 429: 30s → 60s → 120s → 300s → stays at 5 min.
    Backoff is tracked separately from TTL so we never hammer the API while
    rate limited (previously: stale cache caused TTL check to fail every 2s).
    """
    global _cached_usage, _retry_count, _backoff_step, _backoff_until
    ttl = cache_ttl if cache_ttl is not None else _cache_ttl
    now = time.time()

    # Return in-memory cache if fresh AND window hasn't expired
    if _cached_usage and (now - _cached_usage.fetched_at) < ttl:
        return _reset_expired_usage(_cached_usage)

    # ── Proxy shortcut: use proxy-captured rate limit headers if fresh ──
    proxy_usage = _try_proxy_data()
    if proxy_usage is not None:
        _cached_usage = proxy_usage
        return proxy_usage

    # Backoff gate — don't touch API until backoff window clears.
    # This is above the disk-cache check intentionally: if we're rate limited
    # we have cached data already; no need to re-read disk either.
    if now < _backoff_until and cache_ttl != 0:  # cache_ttl=0 = forced retry, skip backoff
        if _cached_usage:
            return _reset_expired_usage(_cached_usage)
        disk = _read_disk_cache(ttl=None)
        if disk:
            _cached_usage = _reset_expired_usage(disk)
            return _cached_usage
        return UsageData(error="Rate limited — no cached data")

    # On cold start (no in-memory cache), try disk cache within TTL
    if not _cached_usage:
        disk = _read_disk_cache(ttl=ttl)
        if disk:
            _cached_usage = disk
            return _cached_usage

    # Reset retry count at entry (prevents stale state from prior calls)
    if cache_ttl != 0:  # cache_ttl=0 is a retry call, don't reset
        _retry_count = 0

    # Read token fresh from file every time
    token, plan = _get_fresh_token()
    if not token:
        if _cached_usage:
            _cached_usage.error = "Token unavailable — showing cached data"
            return _cached_usage
        return UsageData(error="Claude not configured — authenticate with Claude Code")

    try:
        with _authorized_request(
            _USAGE_API_URL,
            token,
            headers={"anthropic-beta": _USAGE_API_BETA, "Accept": "application/json"},
        ) as resp:
            body = json.loads(resp.read(1_000_000))  # 1 MB max

        _retry_count = 0  # reset on success
        _backoff_step = 0   # successful call resets the backoff ladder
        _backoff_until = 0.0

        # Schema version check
        if not _EXPECTED_SCHEMA_KEYS.issubset(body.keys()):
            if _cached_usage:
                _cached_usage.error = "API schema changed — update luna-monitor"
                return _cached_usage
            return UsageData(error="API schema changed — update luna-monitor")

        usage = UsageData(
            five_hour=_parse_window(body.get("five_hour", {})),
            seven_day=_parse_window(body.get("seven_day", {})),
            seven_day_opus=_parse_window(body.get("seven_day_opus")),
            seven_day_sonnet=_parse_window(body.get("seven_day_sonnet")),
            extra_usage=body.get("extra_usage", {}),
            plan=plan,
            fetched_at=time.time(),
        )

        # Track utilization history for burndown
        _usage_history.append((time.time(), usage.five_hour.utilization))

        # Persist to disk (survives restarts, used on 429)
        _write_disk_cache(body, plan)

        _cached_usage = usage
        return usage

    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry_count < 1:
            # Token expired — try refresh once
            _retry_count += 1
            new_token, _ = refresh_and_retry()
            if new_token:
                return fetch_usage(cache_ttl=0)  # bypass cache for retry
            err = "Re-authenticate Claude Code"
        elif e.code == 429:
            # Advance exponential backoff: 30s → 60s → 120s → 300s → stays at 5min
            wait = _BACKOFF_STEPS[min(_backoff_step, len(_BACKOFF_STEPS) - 1)]
            _backoff_until = time.time() + wait
            _backoff_step = min(_backoff_step + 1, len(_BACKOFF_STEPS) - 1)
            # Fall back to stale disk cache (like Pulse), but detect expired windows
            stale = _read_disk_cache(ttl=None)  # no TTL = accept any age
            if stale:
                stale = _reset_expired_usage(stale)
                if not stale.error:
                    stale.error = "Rate limited — showing cached data"
                _cached_usage = stale
                return stale
            err = "Rate limited — will retry"
        else:
            err = f"API error ({e.code})"
        if _cached_usage:
            _cached_usage = _reset_expired_usage(_cached_usage)
            if not _cached_usage.error:
                _cached_usage.error = err
            return _cached_usage
        return UsageData(error=err)

    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        err = "Network error — showing cached data" if _cached_usage else "Network error"
        if _cached_usage:
            _cached_usage = _reset_expired_usage(_cached_usage)
            if not _cached_usage.error:
                _cached_usage.error = err
            return _cached_usage
        return UsageData(error=err)


def _parse_window(data: dict | None) -> UsageWindow:
    """Parse a usage window from the API response. Handles None gracefully.

    The API returns utilization as 0-100 (percentage). We store it as 0-100
    to match Pulse's convention. Clamps to [0, 100].
    """
    if not data:
        return UsageWindow()
    import math
    raw_util = float(data.get("utilization", 0.0))
    if math.isnan(raw_util) or math.isinf(raw_util):
        raw_util = 0.0
    return UsageWindow(
        utilization=max(0.0, min(100.0, raw_util)),
        resets_at=str(data.get("resets_at", "")),
    )


# ── Burndown prediction ─────────────────────────────────────

def get_usage_history() -> deque:
    """Return the usage history deque for the burndown waveform."""
    return _usage_history


def predict_burndown() -> BurndownPrediction:
    """Predict time until usage limit hit using linear regression.

    Uses the last 10 data points from _usage_history (5-hour window utilization).
    """
    if len(_usage_history) < 2:
        return BurndownPrediction(label="Collecting data...")

    points = list(_usage_history)[-10:]

    if len(points) < 3:
        return BurndownPrediction(label="Collecting data...", confidence="low")

    # Detect time gaps (hibernate/sleep) — discard points with >5min gaps
    filtered = [points[0]]
    for i in range(1, len(points)):
        if points[i][0] - points[i - 1][0] > 300:  # 5 minute gap
            filtered = [points[i]]  # restart from after the gap
        else:
            filtered.append(points[i])
    points = filtered
    if len(points) < 3:
        return BurndownPrediction(label="Collecting data...", confidence="low")

    # Linear regression: y = mx + b
    n = len(points)
    t0 = points[0][0]
    xs = [p[0] - t0 for p in points]
    ys = [p[1] for p in points]

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-10:
        return BurndownPrediction(label="Pace: sustainable", confidence="medium")

    slope = (n * sum_xy - sum_x * sum_y) / denom

    if slope <= 0:
        # Only clear history on a real reset (large drop, not rounding artifacts)
        # -1.0 pct/second = dropping 1 percentage point per second, clearly a reset
        if slope < -1.0:
            _usage_history.clear()
            return BurndownPrediction(label="Usage reset detected", confidence="low")
        return BurndownPrediction(label="Pace: sustainable", confidence="medium")

    if abs(slope) < 1e-5:  # ~0.001% per second = negligible (0-100 scale)
        return BurndownPrediction(label="Pace: sustainable", confidence="medium")

    # utilization is 0-100 (percentage)
    current_util = ys[-1]
    remaining = 100.0 - current_util
    if remaining <= 0:
        return BurndownPrediction(minutes_remaining=0, label="Limit reached", confidence="high")

    seconds_to_limit = remaining / slope
    minutes = seconds_to_limit / 60

    confidence = "high" if n >= 8 else ("medium" if n >= 5 else "low")

    if minutes > 600:
        return BurndownPrediction(minutes_remaining=minutes, label="Pace: sustainable", confidence="low")

    return BurndownPrediction(
        minutes_remaining=minutes,
        label=f"~{int(minutes)} min remaining (estimated)",
        confidence=confidence,
    )


def _window_expired(usage: UsageData) -> bool:
    """Check if the 5h window has reset since this data was fetched.

    If resets_at is in the past, the cached utilization is from a dead window
    and should not be shown — the real session has reset to ~0%.
    """
    resets_at = usage.five_hour.resets_at
    if not resets_at:
        return False
    dt = _parse_reset_ts(resets_at)
    if dt is None:
        return False
    return datetime.now(timezone.utc) > dt


def _reset_expired_usage(usage: UsageData) -> UsageData:
    """If the 5h window expired, zero out the stale utilization."""
    if _window_expired(usage):
        usage.five_hour = UsageWindow()  # 0% utilization, no resets_at
        usage.error = "Session reset — awaiting fresh data"
    return usage


def _parse_reset_ts(ts_str: str) -> datetime | None:
    """Parse a reset timestamp that may be ISO 8601 or Unix epoch."""
    if not ts_str:
        return None
    try:
        # Try Unix epoch first (proxy sends these: "1774796400")
        epoch = float(ts_str)
        if epoch > 1_000_000_000:  # sanity: after 2001
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def format_reset_time(iso_str: str) -> str:
    """Format a timestamp (ISO or epoch) into a human-readable 'resets in X' string."""
    if not iso_str:
        return ""
    try:
        dt = _parse_reset_ts(iso_str)
        if dt is None:
            return ""
        now = datetime.now(timezone.utc)
        delta = dt - now
        total_min = max(0, int(delta.total_seconds() / 60))
        if total_min >= 1440:  # >= 24 hours, show days
            days = total_min // 1440
            hours = (total_min % 1440) // 60
            return f"resets in {days}d {hours}h"
        if total_min >= 60:
            hours = total_min // 60
            mins = total_min % 60
            return f"resets in {hours}h {mins}m"
        return f"resets in {total_min}m"
    except (ValueError, TypeError):
        return ""


# ── Disk cache (survives restarts, used on 429/cold start) ───

def _write_disk_cache(usage_dict: dict, plan: str):
    """Write usage data to disk cache. Fire-and-forget (never crash)."""
    try:
        os.makedirs(_DISK_CACHE_DIR, exist_ok=True)
        data = {
            "timestamp": time.time(),
            "plan": plan,
            "usage": {k: v for k, v in usage_dict.items() if k in _USAGE_CACHE_KEYS},
        }
        with open(_DISK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _read_disk_cache(ttl: float | None = None) -> UsageData | None:
    """Read usage data from disk cache. Returns UsageData or None.

    If ttl is None, returns data regardless of age (stale fallback for 429).
    If ttl is set, only returns data younger than ttl seconds.
    """
    try:
        with open(_DISK_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        if ttl is not None and (time.time() - ts) >= ttl:
            return None
        usage_raw = data.get("usage", {})
        if not usage_raw:
            return None
        return UsageData(
            five_hour=_parse_window(usage_raw.get("five_hour")),
            seven_day=_parse_window(usage_raw.get("seven_day")),
            seven_day_opus=_parse_window(usage_raw.get("seven_day_opus")),
            seven_day_sonnet=_parse_window(usage_raw.get("seven_day_sonnet")),
            extra_usage=usage_raw.get("extra_usage", {}),
            plan=data.get("plan", ""),
            fetched_at=ts,
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
        return None


# ── Module helpers ───────────────────────────────────────────

def set_cache_ttl(ttl: float):
    """Override the default cache TTL."""
    global _cache_ttl
    _cache_ttl = ttl


def is_configured() -> bool:
    """Check if Claude credentials exist (without reading tokens)."""
    return os.path.exists(CREDENTIALS_PATH)
