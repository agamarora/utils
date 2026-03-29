"""Claude Activity panel — usage waveform with burndown prediction.

Shows a real-time activity waveform from local JSONL data (always works,
even when the API is rate-limited). The waveform shows when you're actively
using Claude vs idle.

The Status panel above shows utilization % and reset timers.
This panel adds: activity waveform + burndown prediction + token context.
No duplication — each panel has a distinct job.

Uses magenta waveform to visually distinguish from the cyan CPU chart.
"""

import json
import os
from collections import deque
from pathlib import Path

from rich.console import Group
from rich.text import Text

from luna_monitor.collectors.claude import BurndownPrediction
from luna_monitor.collectors.claude_local import (
    LocalUsageData,
    fmt_tokens,
)
from luna_monitor.ui.charts import wave_chart, make_panel
from luna_monitor.ui.colors import BURNDOWN_STYLE


# ── Limit calibration (persisted to disk) ───────────────────

_LIMITS_FILE = str(Path.home() / ".luna-monitor" / "calibrated-limits.json")
_inferred_limit: float | None = None
_loaded_from_disk: bool = False


def _load_limit_from_disk() -> None:
    """Load the previously calibrated limit from disk. Called once on first use."""
    global _inferred_limit, _loaded_from_disk
    if _loaded_from_disk:
        return
    _loaded_from_disk = True
    try:
        with open(_LIMITS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        limit = data.get("five_hour_limit")
        if isinstance(limit, (int, float)) and limit > 0:
            _inferred_limit = float(limit)
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        pass


def _save_limit_to_disk(limit: float) -> None:
    """Persist the calibrated limit to disk. Fire-and-forget."""
    try:
        os.makedirs(os.path.dirname(_LIMITS_FILE), exist_ok=True)
        with open(_LIMITS_FILE, "w", encoding="utf-8") as f:
            json.dump({"five_hour_limit": limit}, f)
    except OSError:
        pass


def _calibrate_limit(utilization_pct: float, local_tokens: int) -> None:
    """Infer the 5h token limit from API utilization + local token count.

    Saves to disk so future sessions work without the API.
    Only calibrates when utilization >= 10% (avoids division noise at low usage).
    Rejects wild swings (>3x change) to avoid persisting bad data from
    multi-device or misaligned time windows.
    """
    global _inferred_limit
    if utilization_pct >= 10.0 and local_tokens > 0:
        new_limit = local_tokens / (utilization_pct / 100.0)
        # Reject obviously wrong calibrations (>3x change from previous)
        if _inferred_limit is not None and _inferred_limit > 0:
            ratio = new_limit / _inferred_limit
            if ratio > 3.0 or ratio < 0.33:
                return  # discard — likely multi-device or window misalignment
        _inferred_limit = new_limit
        _save_limit_to_disk(_inferred_limit)


def _estimate_utilization(local_tokens: int) -> float | None:
    """Estimate utilization % from local tokens using the inferred limit."""
    _load_limit_from_disk()
    if _inferred_limit is not None and _inferred_limit > 0:
        return min(100.0, (local_tokens / _inferred_limit) * 100.0)
    return None


# ── Panel builder ───────────────────────────────────────────

def build_claude_burndown(
    local_data: LocalUsageData,
    burn_history: deque,
    console_width: int,
    utilization_pct: float | None = None,
    prediction: BurndownPrediction | None = None,
) -> object:
    """Build the Claude Activity panel.

    Args:
        local_data: LocalUsageData from claude_local.collect().
        burn_history: Deque of (timestamp, tokens_per_min) pairs.
        console_width: Terminal width for chart sizing.
        utilization_pct: API-reported 5h utilization (0-100), or None if unavailable.
        prediction: Burndown prediction from predict_burndown(), or None.
    """
    # Calibrate limit when we have both API and local data
    if utilization_pct is not None and utilization_pct > 0 and local_data.tokens_5h > 0:
        _calibrate_limit(utilization_pct, local_data.tokens_5h)

    # Title: just "Claude Activity" — no % duplication with Status panel
    title = "Claude Activity"

    # Extract raw rates and normalize to 0-100 using session peak
    raw_rates = [r for _, r in burn_history]

    if len(raw_rates) < 2:
        # Not enough data yet — show what we have
        info = Text()
        if local_data.tokens_5h > 0:
            info.append(f"5h: {fmt_tokens(local_data.tokens_5h)} tok", style="dim")
        else:
            info.append("Waiting for activity...", style="dim italic")
        return make_panel(info, title, claude=True)

    max_rate = max(raw_rates)
    if max_rate > 0:
        normalized = deque(
            (min(100.0, r / max_rate * 100) for r in raw_rates),
            maxlen=burn_history.maxlen or 300,
        )
    else:
        normalized = deque([0.0] * len(raw_rates), maxlen=burn_history.maxlen or 300)

    chart = wave_chart(normalized, console_width, height=5, style=BURNDOWN_STYLE)

    # Info line: prediction (if meaningful) + token context
    info = Text()

    # Show prediction only if it has a real estimate (not "Collecting data...")
    if prediction and prediction.minutes_remaining is not None:
        style = "magenta bold" if prediction.confidence == "high" else "magenta"
        if prediction.minutes_remaining <= 120:
            style = "red bold"
        info.append(prediction.label, style=style)

    # Token context
    if local_data.tokens_5h > 0:
        if info.plain:
            info.append("  ·  ", style="dim")
        info.append(f"5h: {fmt_tokens(local_data.tokens_5h)} tok", style="dim")

    # Fallback when nothing to show
    if not info.plain:
        info.append("idle", style="dim italic")

    return make_panel(Group(*chart, info), title, claude=True)
