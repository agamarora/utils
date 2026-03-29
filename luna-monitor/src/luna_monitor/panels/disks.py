"""Disks panel: active time %, read/write speeds, storage usage."""

from rich.console import Group
from rich.text import Text

from luna_monitor.ui.charts import hbar, fmt_bytes, make_panel
from luna_monitor.ui.colors import pct_color, io_color


def build_disks(
    disks: list[tuple[str, object]],
    disk_active: dict,
    disk_io_speeds: dict,
    drive_to_disk: dict,
) -> object:
    """Build the disks panel.

    Args:
        disks: List of (drive_path, psutil.disk_usage) tuples.
        disk_active: {drive: active_pct} from PDH.
        disk_io_speeds: {PhysicalDriveX: (read_bps, write_bps)}.
        drive_to_disk: {drive: PhysicalDriveX} mapping.
    """
    if not disks:
        return make_panel(Text("No drives configured", style="dim"), "Disks")

    lines = []
    for drive, usage in disks:
        phys_disk = drive_to_disk.get(drive)
        active = disk_active.get(drive, 0.0)
        r_spd, w_spd = disk_io_speeds.get(phys_disk, (0, 0)) if phys_disk else (0, 0)

        row = Text()
        row.append(f"{drive:<5}", style="bold white")
        row.append_text(hbar(active, width=18))
        row.append(f"  {active:4.1f}%", style=pct_color(active) + " bold")
        row.append(f"  R {fmt_bytes(r_spd)}/s", style=io_color(r_spd))
        row.append(f"  W {fmt_bytes(w_spd)}/s", style=io_color(w_spd))
        row.append(f"  ({usage.percent:.0f}% full)", style="dim")
        lines.append(row)

    return make_panel(Group(*lines), "Disks")
