"""Temperature panel: CPU and GPU temperatures from multiple sources."""

from rich.console import Group
from rich.table import Table
from rich.text import Text

from luna_monitor.ui.charts import make_panel
from luna_monitor.ui.colors import temp_color


def _short_name(name: str) -> str:
    """Shorten sensor name for display."""
    n = name.replace("CPU ", "").replace(" Temperature", "")
    n = n.replace("Core #", "Core ").replace("Package", "Pkg")
    return n[:12]


def build_temps(temps: dict, lhm_running: bool = False) -> object:
    """Build the temperature panel.

    Args:
        temps: {sensor_name: celsius} dict from all sources.
        lhm_running: Whether LHM data was available.
    """
    cpu_visible = any(
        k for k in temps
        if any(x in k.lower() for x in ("package", "tdie", "cpu core"))
    )

    # Priority sort: important sensors first
    priority = ["CPU Package", "Package", "Tdie", "CPU Core", "GPU"]
    seen = {}
    for key in priority:
        for k, v in temps.items():
            if key.lower() in k.lower() and k not in seen:
                seen[k] = v
    for k, v in temps.items():
        if k not in seen:
            seen[k] = v

    sensors = list(seen.items())[:8]

    if not sensors:
        if not lhm_running:
            content = Text(
                "Enable: LHM → Options → Remote Web Server → Start",
                style="yellow italic",
            )
        else:
            content = Text("No sensors detected", style="dim")
        return make_panel(content, "Temps")

    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column(width=12, no_wrap=True)
    tbl.add_column(width=6, justify="right")
    tbl.add_column(width=12, no_wrap=True)
    tbl.add_column(width=6, justify="right")

    for i in range(0, len(sensors), 2):
        k1, v1 = sensors[i]
        n1 = Text(_short_name(k1), style="dim")
        t1 = Text(f"{v1:.0f}°C", style=temp_color(v1) + " bold")
        if i + 1 < len(sensors):
            k2, v2 = sensors[i + 1]
            n2 = Text(_short_name(k2), style="dim")
            t2 = Text(f"{v2:.0f}°C", style=temp_color(v2) + " bold")
        else:
            n2, t2 = Text(""), Text("")
        tbl.add_row(n1, t1, n2, t2)

    if not cpu_visible:
        hint = Text()
        if lhm_running:
            hint.append("CPU temp not in sensor set", style="dim italic")
        else:
            hint.append(
                "Enable: LHM → Options → Remote Web Server → Start",
                style="yellow italic",
            )
        return make_panel(Group(tbl, hint), "Temps")

    return make_panel(tbl, "Temps")
