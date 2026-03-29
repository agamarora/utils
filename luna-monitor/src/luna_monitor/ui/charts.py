"""Shared rendering utilities: waveform charts, bars, format helpers, panel wrapper."""

from collections import deque

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box as rich_box

from luna_monitor.ui.colors import pct_color, SYSTEM_BORDER, CLAUDE_BORDER

BLOCKS = " ▁▂▃▄▅▆▇█"  # 9 levels for smooth waveform

DEFAULT_BAR_W = 20
DEFAULT_CHART_H = 7


def fmt_bytes(n: float) -> str:
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_speed(mbps: float) -> str:
    """Format network speed (in Mbps) to human-readable string."""
    if mbps >= 1000:
        return f"{mbps / 1000:.1f} Gb/s"
    if mbps >= 1:
        return f"{mbps:.1f} Mb/s"
    if mbps >= 0.001:
        return f"{mbps * 1000:.0f} Kb/s"
    return "0 b/s"


def hbar(pct: float, width: int = DEFAULT_BAR_W) -> Text:
    """Horizontal bar showing a percentage. Uses pct_color for fill color."""
    filled = max(0, min(width, int(pct / 100 * width)))
    t = Text()
    t.append("█" * filled, style=pct_color(pct))
    t.append("░" * (width - filled), style="bright_black")
    return t


def wave_chart(
    history: deque,
    console_width: int,
    height: int = DEFAULT_CHART_H,
    style: str = "cyan",
) -> list[Text]:
    """Filled area waveform chart (like Task Manager CPU graph).

    Args:
        history: deque of float values 0-100.
        console_width: current terminal width (used to size the chart).
        height: number of rows for the chart.
        style: Rich style for the filled area.

    Returns:
        List of Text objects, one per row (top to bottom).
    """
    width = max(console_width - 4, 20)  # panel border + padding
    data = list(history)[-width:]
    if len(data) < width:
        data = [0.0] * (width - len(data)) + data

    lines = []
    for row in range(height):
        row_top = (height - row) / height * 100
        row_bot = (height - row - 1) / height * 100
        row_range = row_top - row_bot
        line = Text()
        for val in data:
            if val >= row_top:
                line.append("█", style=style)
            elif val <= row_bot:
                line.append(" ")
            else:
                frac = (val - row_bot) / row_range
                line.append(BLOCKS[min(8, int(frac * 8))], style=style)
        lines.append(line)
    return lines


def make_panel(content, title: str, claude: bool = False) -> Panel:
    """Wrap content in a Rich Panel with consistent styling.

    Args:
        content: Rich renderable (Text, Group, Table, etc.)
        title: Panel title text.
        claude: If True, use Claude panel border color.
    """
    border = CLAUDE_BORDER if claude else SYSTEM_BORDER
    return Panel(
        content,
        title=f"[bold white]{title}[/bold white]",
        border_style=border,
        box=rich_box.ROUNDED,
        padding=(0, 1),
    )
