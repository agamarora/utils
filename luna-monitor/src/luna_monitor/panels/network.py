"""Network panel: current, average, and peak download/upload speeds."""

from rich.console import Group
from rich.text import Text

from luna_monitor.ui.charts import fmt_speed, make_panel


def build_network(rx_now: float, tx_now: float, stats: dict) -> object:
    """Build the network panel.

    Args:
        rx_now: Current download speed in Mbps.
        tx_now: Current upload speed in Mbps.
        stats: Dict with rx_avg, tx_avg, rx_peak, tx_peak (from get_network_stats).
    """
    dl = Text()
    dl.append("↓  ", style="cyan bold")
    dl.append(f"now {fmt_speed(rx_now):<13}", style="cyan")
    dl.append(f"avg {fmt_speed(stats.get('rx_avg', 0)):<13}", style="dim")
    dl.append(f"peak {fmt_speed(stats.get('rx_peak', 0))}", style="dim")

    ul = Text()
    ul.append("↑  ", style="magenta bold")
    ul.append(f"now {fmt_speed(tx_now):<13}", style="magenta")
    ul.append(f"avg {fmt_speed(stats.get('tx_avg', 0)):<13}", style="dim")
    ul.append(f"peak {fmt_speed(stats.get('tx_peak', 0))}", style="dim")

    return make_panel(Group(dl, ul), "Network")
