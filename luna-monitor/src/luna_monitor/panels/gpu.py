"""GPU panel: utilization bar, VRAM, temperature."""

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box as rich_box

from luna_monitor.ui.charts import hbar, fmt_bytes, make_panel
from luna_monitor.ui.colors import pct_color, temp_color, SYSTEM_BORDER


def build_gpu_lines(gpu_data: dict | None) -> list[Text]:
    """Build GPU lines. gpu_data is from collectors.gpu.collect_gpu()."""
    if gpu_data is None:
        return [Text("No GPU data", style="dim")]

    lines = []
    pct = gpu_data["pct"]
    row = Text()
    row.append_text(hbar(pct))
    row.append(f"  {pct:.1f}%", style=pct_color(pct) + " bold")
    lines.append(row)

    if gpu_data.get("mem_used") is not None:
        lines.append(Text(
            f"VRAM  {fmt_bytes(gpu_data['mem_used'])} / {fmt_bytes(gpu_data['mem_total'])}",
            style="dim",
        ))

    temp = gpu_data.get("temp")
    if temp is not None:
        lines.append(Text(f"Temp  {temp}°C", style=temp_color(temp) + " bold"))

    return lines


def build_mem_gpu(ram_lines: list, gpu_lines: list, gpu_title: str = "GPU") -> Table:
    """Build side-by-side Memory + GPU panels with matched heights.

    Args:
        ram_lines: List of Text objects from memory.build_memory_lines().
        gpu_lines: List of Text objects from build_gpu_lines().
        gpu_title: Title for the GPU panel (GPU name, truncated).
    """
    h = max(len(ram_lines), len(gpu_lines)) + 2
    side = Table(box=None, padding=0, show_header=False, expand=True)
    side.add_column(ratio=3)
    side.add_column(ratio=2)
    side.add_row(
        Panel(
            Group(*ram_lines),
            title=f"[bold white]Memory[/bold white]",
            border_style=SYSTEM_BORDER,
            box=rich_box.ROUNDED,
            padding=(0, 1),
            height=h,
        ),
        Panel(
            Group(*gpu_lines),
            title=f"[bold white]{gpu_title}[/bold white]",
            border_style=SYSTEM_BORDER,
            box=rich_box.ROUNDED,
            padding=(0, 1),
            height=h,
        ),
    )
    return side
