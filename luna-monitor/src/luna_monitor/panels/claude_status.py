"""Claude Status panel — the soul of luna-monitor.

Shows: plan tier, session (5h) usage %, weekly (7d) usage %,
per-model breakdown, reset timers, proxy + API health. Distinct cyan border.
"""

from rich.console import Group
from rich.text import Text

from luna_monitor.collectors.claude import UsageData, format_reset_time
from luna_monitor.collectors.rate_limit import ProxyHealth
from luna_monitor.ui.charts import hbar, make_panel
from luna_monitor.ui.colors import pct_color


def build_claude_status(
    usage: UsageData,
    proxy_running: bool = False,
    proxy_enabled: bool | None = None,
    proxy_health: ProxyHealth | None = None,
) -> object:
    """Build the Claude Status panel.

    Args:
        usage: UsageData from fetch_usage(). May have .error set.
        proxy_running: Whether the embedded proxy is currently active.
        proxy_enabled: User's proxy preference (None = not decided).
        proxy_health: ProxyHealth from collect_proxy_health(), or None.
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

    # Data source + API health status line
    source = usage.extra_usage.get("_source", "")
    if source == "proxy" and proxy_health and proxy_health.proxy_up:
        status = _format_api_health(proxy_health)
        lines.append(status)
    elif source == "proxy":
        lines.append(Text("via proxy", style="green dim"))
    elif proxy_running:
        try:
            from luna_monitor.proxy.watchdog import is_recovering
            if is_recovering:
                lines.append(Text("Proxy: restarting...", style="yellow dim"))
            else:
                lines.append(Text("via proxy (waiting for data)", style="dim"))
        except ImportError:
            lines.append(Text("via proxy", style="dim"))
    elif proxy_enabled is False:
        pass
    elif usage.fetched_at and not usage.error:
        lines.append(Text("via API", style="dim"))

    # Only show errors that indicate a real problem the user should act on
    if usage.error and "cached" not in usage.error.lower() and "rate" not in usage.error.lower():
        lines.append(Text(f"⚠ {usage.error}", style="yellow dim"))

    return make_panel(Group(*lines), "Claude Code", claude=True)


def _format_api_health(health: ProxyHealth) -> Text:
    """Format the API health status line from proxy health data."""
    t = Text()
    t.append("via proxy", style="green dim")

    # Latency
    if health.last_latency_ms > 0:
        lat = health.last_latency_ms
        lat_style = "green dim" if lat < 2000 else ("yellow dim" if lat < 5000 else "red dim")
        if lat >= 1000:
            t.append(f"  {lat / 1000:.1f}s", style=lat_style)
        else:
            t.append(f"  {lat:.0f}ms", style=lat_style)

    # Request count
    if health.requests_proxied > 0:
        t.append(f"  {health.requests_proxied} reqs", style="dim")

    # Error indicator (only show if errors exist)
    if health.api_errors_429 > 0:
        t.append(f"  {health.api_errors_429} 429s", style="red dim")
    elif health.api_errors_total > 0:
        t.append(f"  {health.api_errors_total} errors", style="yellow dim")

    return t
