"""Claude Status panel — the soul of luna-monitor.

Shows: plan tier, session (5h) usage %, weekly (7d) usage %,
per-model breakdown, reset timers. Distinct cyan border.
"""

from rich.console import Group
from rich.text import Text

from luna_monitor.collectors.claude import UsageData, format_reset_time
from luna_monitor.ui.charts import hbar, make_panel
from luna_monitor.ui.colors import pct_color


def build_claude_status(usage: UsageData) -> object:
    """Build the Claude Status panel.

    Args:
        usage: UsageData from fetch_usage(). May have .error set.
    """
    # Error state
    if usage.error and not usage.fetched_at:
        return make_panel(
            Text(usage.error, style="yellow italic"),
            "Claude Code",
            claude=True,
        )

    lines = []

    # Plan tier
    if usage.plan:
        lines.append(Text(f"Plan: {usage.plan}", style="bold white"))

    # 5-hour session usage (utilization is already 0-100 from API)
    pct_5h = usage.five_hour.utilization
    row = Text()
    row.append("Session  ", style="dim")
    row.append_text(hbar(pct_5h))
    row.append(f"  {pct_5h:.0f}%", style=pct_color(pct_5h) + " bold")
    reset_str = format_reset_time(usage.five_hour.resets_at)
    if reset_str:
        row.append(f"  ({reset_str})", style="dim")
    lines.append(row)

    # 7-day weekly usage
    pct_7d = usage.seven_day.utilization
    row = Text()
    row.append("Weekly   ", style="dim")
    row.append_text(hbar(pct_7d))
    row.append(f"  {pct_7d:.0f}%", style=pct_color(pct_7d) + " bold")
    reset_str = format_reset_time(usage.seven_day.resets_at)
    if reset_str:
        row.append(f"  ({reset_str})", style="dim")
    lines.append(row)

    # Per-model breakdown (if available)
    if usage.seven_day_opus.utilization > 0 or usage.seven_day_sonnet.utilization > 0:
        opus_pct = usage.seven_day_opus.utilization
        sonnet_pct = usage.seven_day_sonnet.utilization
        breakdown = Text()
        breakdown.append("         ", style="dim")
        breakdown.append(f"Opus {opus_pct:.0f}%", style="dim")
        breakdown.append("  ", style="dim")
        breakdown.append(f"Sonnet {sonnet_pct:.0f}%", style="dim")
        lines.append(breakdown)

    # Data source indicator
    source = usage.extra_usage.get("_source", "")
    if source == "proxy":
        lines.append(Text("via proxy", style="green dim"))
    elif usage.fetched_at and not usage.error:
        lines.append(Text("via API", style="dim"))

    # Only show errors that indicate a real problem the user should act on
    # "Rate limited" and "showing cached data" are transient — don't clutter the UI
    if usage.error and "cached" not in usage.error.lower() and "rate" not in usage.error.lower():
        lines.append(Text(f"⚠ {usage.error}", style="yellow dim"))

    return make_panel(Group(*lines), "Claude Code", claude=True)
