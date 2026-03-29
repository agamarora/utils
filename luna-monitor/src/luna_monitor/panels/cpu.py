"""CPU panel: waveform chart + utilization + frequency."""

from collections import deque

from rich.console import Group
from rich.text import Text

from luna_monitor.ui.charts import wave_chart, make_panel
from luna_monitor.ui.colors import pct_color, CPU_STYLE


def build_cpu(
    avg_pct: float,
    cpu_history: deque,
    console_width: int,
    freq_str: str = "",
    throttled: bool = False,
) -> object:
    """Build the CPU panel with waveform chart.

    Args:
        avg_pct: Average CPU utilization (0-100).
        cpu_history: Deque of historical CPU percentages.
        console_width: Terminal width for chart sizing.
        freq_str: Formatted frequency string (e.g., "4.10 GHz").
        throttled: Whether CPU is throttling.
    """
    chart = wave_chart(cpu_history, console_width, style=CPU_STYLE)
    info = Text()
    info.append(f"Utilisation {avg_pct:.1f}%", style=pct_color(avg_pct) + " bold")
    if freq_str:
        info.append(f"    Speed {freq_str}", style="dim")
    if throttled:
        info.append("   ⚠ THROTTLING", style="red bold")
    return make_panel(Group(*chart, info), "CPU")
