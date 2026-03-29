"""Claude Code local data collector — reads JSONL files, no API required.

Parses ~/.claude/projects/**/*.jsonl to extract per-message token counts.
Provides burn rate (tokens/min), 5h/7d totals, and model breakdown.
Always works even when the Anthropic usage API is rate-limited.

JSONL line format (confirmed from sampling, March 2026):
  {
    "timestamp": "2026-03-29T07:16:15.649Z",
    "message": {
      "model": "claude-opus-4-6",
      "usage": {
        "input_tokens": 3,
        "cache_creation_input_tokens": 9804,
        "cache_read_input_tokens": 11497,
        "output_tokens": 30
      }
    }
  }

Token weighting (quota-relevant, excludes cache reads):
  input_tokens                  1.0x  (new content entering the system)
  cache_creation_input_tokens   1.0x  (loading files into cache)
  cache_read_input_tokens       0.0x  (excluded — re-reads of existing context)
  output_tokens                 1.0x  (what Claude actually wrote)

Subagent files (subagents/*.jsonl) are excluded — they represent sub-calls
from parent sessions and would double-count tokens if included.
"""

import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ────────────────────────────────────────────────

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

_CACHE_TTL: float = 2.0       # seconds — matches the 2s refresh loop
_WINDOW_5H: float = 5 * 3600  # seconds
_WINDOW_7D: float = 7 * 86400  # seconds
_WINDOW_10M: float = 10 * 60   # seconds — burn rate window

# Token weighting: exclude cache_read (re-reads of existing context, not new consumption)
# Cache reads inflate numbers massively (106M raw in a 5h session) without representing
# real quota usage. Input + cache_create + output = "new work done."
_W_INPUT: float = 1.0
_W_CACHE_CREATE: float = 1.0
_W_CACHE_READ: float = 0.0
_W_OUTPUT: float = 1.0

# Human-readable model name prefixes
_MODEL_SHORT: dict[str, str] = {
    "claude-opus": "Opus",
    "claude-sonnet": "Sonnet",
    "claude-haiku": "Haiku",
}


# ── Data types ───────────────────────────────────────────────

@dataclass
class LocalUsageData:
    """Token usage stats derived from local JSONL files."""
    tokens_5h: int = 0
    tokens_7d: int = 0
    requests_5h: int = 0             # deduped API call count in last 5h
    burn_rate: float = 0.0           # tokens/min over last 10 min (excl. cache_read)
    model_breakdown: dict = field(default_factory=dict)  # model_key → int tokens
    collected_at: float = 0.0


# ── Module state ─────────────────────────────────────────────

_cached: LocalUsageData | None = None
_cached_at: float = 0.0
_burn_history: deque = deque(maxlen=300)  # (epoch_float, burn_rate_tokens_per_min)


# ── Public API ───────────────────────────────────────────────

def get_burn_history() -> deque:
    """Return the burn rate history deque for the burndown waveform.

    Each entry is (timestamp_epoch, tokens_per_min). The panel normalizes
    the values to 0-100 using the session max.
    """
    return _burn_history


def collect(cache_ttl: float = _CACHE_TTL) -> LocalUsageData:
    """Read JSONL files and return token usage stats.

    Returns cached result if within cache_ttl seconds. Filters out subagent
    paths and files older than 7 days by mtime before opening them.
    Never raises — returns empty LocalUsageData on any error.
    """
    global _cached, _cached_at

    now = time.time()
    if _cached is not None and (now - _cached_at) < cache_ttl:
        return _cached

    result = _scan_files(now)
    _cached = result
    _cached_at = now

    # Append (timestamp, burn_rate) to history for the waveform
    _burn_history.append((now, result.burn_rate))

    return result


def model_short(model_key: str) -> str:
    """Return a short display name for a model key.

    "claude-opus-4-6" → "Opus"
    "claude-sonnet-4-6" → "Sonnet"
    Unknown models returned as-is.
    """
    for prefix, short in _MODEL_SHORT.items():
        if model_key.startswith(prefix):
            return short
    return model_key


def fmt_tokens(n: float) -> str:
    """Format a token count for display: 1234567 → '1.2M', 12345 → '12.3K'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def fmt_rate(tokens_per_min: float) -> str:
    """Format a burn rate for display: 12345.6 → '12.3K tok/min'."""
    return f"{fmt_tokens(tokens_per_min)} tok/min"


# ── Internal ─────────────────────────────────────────────────

def _weighted_tokens(usage: dict) -> float:
    """Compute weighted token count from a usage dict. Missing keys default to 0."""
    return (
        usage.get("input_tokens", 0) * _W_INPUT
        + usage.get("cache_creation_input_tokens", 0) * _W_CACHE_CREATE
        + usage.get("cache_read_input_tokens", 0) * _W_CACHE_READ
        + usage.get("output_tokens", 0) * _W_OUTPUT
    )


def _parse_ts(ts_str: str) -> float | None:
    """Parse ISO 8601 timestamp string to epoch float. Returns None on failure.

    Handles the 'Z' suffix by replacing with '+00:00' for Python < 3.11 compat.
    """
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def _scan_files(now: float) -> LocalUsageData:
    """Scan JSONL files and compute token totals. Never raises."""
    cutoff_5h = now - _WINDOW_5H
    cutoff_7d = now - _WINDOW_7D
    cutoff_10m = now - _WINDOW_10M

    # Collect (timestamp_epoch, weighted_tokens, model_key) for all messages in 7d
    messages: list[tuple[float, float, str]] = []

    # Deduplication set: Claude Code logs streaming responses multiple times with
    # the same requestId+messageId. We keep only the first occurrence (matches ccusage).
    seen_keys: set[tuple[str, str]] = set()

    try:
        all_files = list(CLAUDE_PROJECTS_DIR.glob("**/*.jsonl"))
    except (PermissionError, OSError):
        return LocalUsageData()

    for path in all_files:
        # Subagent files live in a 'subagents' directory — skip them
        # They are sub-calls from parent sessions; including them double-counts.
        if "subagents" in path.parts:
            continue

        # Skip files older than 7d by mtime — avoids reading large old files
        try:
            if path.stat().st_mtime < cutoff_7d:
                continue
        except OSError:
            continue

        try:
            _read_file(path, cutoff_7d, messages, seen_keys)
        except (PermissionError, OSError):
            continue

    # Compute window totals from collected messages
    tokens_5h = int(sum(wt for ts, wt, _ in messages if ts >= cutoff_5h))
    tokens_7d = int(sum(wt for _, wt, _ in messages))  # all entries are within 7d

    tokens_10m = sum(wt for ts, wt, _ in messages if ts >= cutoff_10m)
    burn_rate = tokens_10m / 10.0  # tokens per minute (average over 10min window)

    # Request count: number of distinct API calls in the 5h window
    requests_5h = sum(1 for ts, _, _ in messages if ts >= cutoff_5h)

    # Model breakdown: sum weighted tokens per model
    model_breakdown: dict[str, int] = {}
    for _, wt, model in messages:
        model_breakdown[model] = model_breakdown.get(model, 0) + int(wt)

    return LocalUsageData(
        tokens_5h=tokens_5h,
        tokens_7d=tokens_7d,
        requests_5h=requests_5h,
        burn_rate=burn_rate,
        model_breakdown=model_breakdown,
        collected_at=now,
    )


def _read_file(
    path: Path,
    cutoff_7d: float,
    messages: list,
    seen_keys: set,
) -> None:
    """Read one JSONL file and append valid (ts, weighted_tokens, model) to messages.

    Skips bad lines silently. Uses errors='replace' to handle non-UTF-8 bytes.
    Deduplicates by requestId+messageId — Claude Code logs streaming responses
    multiple times with the same key but growing output_tokens. We keep the first
    occurrence (matches ccusage behaviour).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                ts_str = entry.get("timestamp")
                if not ts_str:
                    continue
                ts = _parse_ts(ts_str)
                if ts is None or ts < cutoff_7d:
                    continue

                msg = entry.get("message")
                if not isinstance(msg, dict):
                    continue

                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue

                # Deduplication: skip streaming duplicates (same API call logged multiple times)
                req_id = entry.get("requestId")
                msg_id = msg.get("id")
                if req_id is not None and msg_id is not None:
                    dedup_key = (req_id, msg_id)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                model = msg.get("model") or "unknown"
                wt = _weighted_tokens(usage)
                messages.append((ts, wt, model))

    except (PermissionError, OSError):
        pass  # skip unreadable files silently
