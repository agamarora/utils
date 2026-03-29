"""Memory panel: RAM and swap usage bars."""

from rich.console import Group
from rich.text import Text

from luna_monitor.ui.charts import hbar, fmt_bytes, make_panel
from luna_monitor.ui.colors import pct_color


def build_memory_lines(ram, swap) -> list[Text]:
    """Build memory lines for the panel. Returns list of Text objects."""
    lines = []
    bar = hbar(ram.percent)
    row = Text()
    row.append("RAM   ", style="dim")
    row.append_text(bar)
    row.append(f"  {ram.percent:.1f}%", style=pct_color(ram.percent) + " bold")
    lines.append(row)
    lines.append(Text(f"      {fmt_bytes(ram.used)} / {fmt_bytes(ram.total)}", style="dim"))

    if swap.total > 0:
        sbar = hbar(swap.percent)
        srow = Text()
        srow.append("Swap  ", style="dim")
        srow.append_text(sbar)
        srow.append(f"  {swap.percent:.1f}%", style=pct_color(swap.percent) + " bold")
        lines.append(srow)
        lines.append(Text(f"      {fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}", style="dim"))

    return lines


def build_memory(ram, swap) -> object:
    """Build standalone memory panel."""
    lines = build_memory_lines(ram, swap)
    return make_panel(Group(*lines), "Memory")
