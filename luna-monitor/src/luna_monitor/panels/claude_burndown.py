"""Claude Burndown panel — token velocity waveform with model breakdown.

The killer feature: a real-time burn rate chart sourced from local JSONL files,
always works even when the Anthropic API is rate-limited.

Uses magenta waveform to visually distinguish from the cyan CPU chart.
The waveform auto-scales to the session peak (session-max normalization).
"""

from collections import deque

from rich.console import Group
from rich.text import Text

from luna_monitor.collectors.claude_local import (
    LocalUsageData,
    fmt_rate,
    fmt_tokens,
    model_short,
)
from luna_monitor.ui.charts import wave_chart, make_panel
from luna_monitor.ui.colors import BURNDOWN_STYLE


def build_claude_burndown(
    local_data: LocalUsageData,
    burn_history: deque,
    console_width: int,
) -> object:
    """Build the Claude Burndown panel.

    Args:
        local_data: LocalUsageData from claude_local.collect().
        burn_history: Deque of (timestamp, tokens_per_min) pairs.
        console_width: Terminal width for chart sizing.
    """
    # Extract raw rates and normalize to 0-100 using session peak
    raw_rates = [r for _, r in burn_history]

    if len(raw_rates) < 2:
        return make_panel(
            Text("Collecting local data...", style="dim italic"),
            "Usage Burndown",
            claude=True,
        )

    max_rate = max(raw_rates)
    if max_rate > 0:
        normalized = deque(
            (min(100.0, r / max_rate * 100) for r in raw_rates),
            maxlen=burn_history.maxlen or 300,
        )
    else:
        normalized = deque([0.0] * len(raw_rates), maxlen=burn_history.maxlen or 300)

    chart = wave_chart(normalized, console_width, height=5, style=BURNDOWN_STYLE)

    # Title shows current burn rate
    rate_str = fmt_rate(local_data.burn_rate) if local_data.burn_rate > 0 else "idle"
    title = f"Usage Burndown — {rate_str}"

    # Info line: burn rate + model breakdown
    info = Text()
    info.append(rate_str, style="magenta bold")

    breakdown = _format_breakdown(local_data.model_breakdown)
    if breakdown:
        info.append("  ", style="dim")
        info.append(breakdown, style="dim")

    # 5h total
    if local_data.tokens_5h > 0:
        info.append(f"  ·  5h: {fmt_tokens(local_data.tokens_5h)} tok", style="dim")

    return make_panel(Group(*chart, info), title, claude=True)


def _format_breakdown(model_breakdown: dict) -> str:
    """Format model breakdown as a compact string.

    {"claude-opus-4-6": 1200000, "claude-sonnet-4-6": 450000} →
    "Opus 1.2M  Sonnet 450K"

    Sorts by token count descending, shows top 3 models.
    """
    if not model_breakdown:
        return ""

    entries = sorted(model_breakdown.items(), key=lambda kv: kv[1], reverse=True)
    parts = []
    for model_key, tokens in entries[:3]:
        short = model_short(model_key)
        parts.append(f"{short} {fmt_tokens(tokens)}")
    return "  ".join(parts)
