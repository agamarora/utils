"""Main application loop — Rich Live compositor.

Wires all collectors and panels into a single full-screen dashboard.
Claude panels on top (the soul), system panels below (the body).
"""

import sys
import time

import psutil
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from luna_monitor.collectors import system as sys_collector
from luna_monitor.collectors.gpu import GPU_AVAILABLE, GPU_NAME, collect_gpu
from luna_monitor.collectors.claude import (
    is_configured as claude_configured,
    fetch_usage,
    set_cache_ttl,
    predict_burndown,
)
from luna_monitor.collectors.claude_local import collect as collect_local, get_burn_history
from luna_monitor.collectors.rate_limit import collect_proxy_health

from luna_monitor.panels.cpu import build_cpu
from luna_monitor.panels.memory import build_memory_lines
from luna_monitor.panels.gpu import build_gpu_lines, build_mem_gpu
from luna_monitor.panels.disks import build_disks
from luna_monitor.panels.network import build_network
from luna_monitor.panels.temps import build_temps
from luna_monitor.panels.processes import build_procs
from luna_monitor.panels.claude_status import build_claude_status
from luna_monitor.panels.claude_burndown import build_claude_burndown

from luna_monitor.ui.charts import make_panel

_console = Console()

# Platform-specific imports
if sys.platform == "win32":
    from luna_monitor.collectors.platform_win import (
        init_pdh,
        collect_disk_active,
        collect_temps,
        get_freq_str,
        get_drive_to_disk,
    )
else:
    from luna_monitor.collectors.platform_posix import (
        init_pdh,
        collect_disk_active,
        collect_temps,
        get_freq_str,
        get_drive_to_disk,
    )


def _min_terminal_check() -> bool:
    """Return False if terminal is too small."""
    return _console.width >= 60 and _console.height >= 15


def _too_small_message() -> Text:
    t = Text()
    t.append("Terminal too small\n", style="bold red")
    t.append(f"Need at least 60x15, got {_console.width}x{_console.height}\n", style="dim")
    t.append("Resize your terminal window to continue.", style="dim")
    return t


def _getting_started() -> object:
    """Show getting started panel when Claude is not configured."""
    lines = Text()
    lines.append("Authenticate with Claude Code to enable usage tracking:\n", style="dim")
    lines.append("  claude login\n", style="cyan bold")
    lines.append("\nSystem monitoring panels are active below.", style="dim")
    return make_panel(lines, "Getting Started — Claude Code", claude=True)


def build_display(config: dict) -> Group:
    """Build the full dashboard — all panels composed into a single Group."""
    if not _min_terminal_check():
        return Group(_too_small_message())

    parts = []
    gpu_enabled = config.get("gpu_enabled", True)
    claude_enabled = config.get("claude_enabled", True)
    drives = config.get("drives", ["C:\\"])
    width = _console.width

    # ── Claude panels (top of screen, the soul) ──────────────
    if claude_enabled:
        if claude_configured():
            usage = fetch_usage(cache_ttl=config.get("cache_ttl_seconds"))

            # Pass proxy status + API health to status panel
            proxy_running = config.get("_proxy_running", False)
            proxy_enabled = config.get("proxy_enabled")
            proxy_port = config.get("_proxy_port", config.get("proxy_port", 9120))
            proxy_health = collect_proxy_health(port=proxy_port) if proxy_running else None
            parts.append(build_claude_status(
                usage,
                proxy_running=proxy_running,
                proxy_enabled=proxy_enabled,
                proxy_health=proxy_health,
            ))

            # Activity panel — waveform + burndown prediction + utilization %
            local_data = collect_local()
            burn_history = get_burn_history()
            utilization_pct = usage.five_hour.utilization if usage.fetched_at else None
            prediction = predict_burndown()
            parts.append(build_claude_burndown(
                local_data, burn_history, width, utilization_pct, prediction,
            ))
        else:
            parts.append(_getting_started())

    # ── CPU panel ────────────────────────────────────────────
    avg_pct, _ = sys_collector.collect_cpu()

    # Get frequency: LHM real clock if available, else psutil
    lhm_freq, lhm_mhz = get_freq_str()
    if lhm_freq:
        freq_str = lhm_freq
        avg_mhz = lhm_mhz
    else:
        freq_str, avg_mhz = sys_collector.collect_cpu_freq()

    # Throttle detection: compare current speed to psutil's reported max
    # (avoids hardcoding a specific CPU's base clock)
    base_freq = psutil.cpu_freq()
    base_max = base_freq.max if base_freq and base_freq.max > 0 else 0
    throttled = bool(base_max > 0 and avg_mhz > 0 and avg_mhz < base_max * 0.70)
    cpu_history = sys_collector.get_cpu_history()
    parts.append(build_cpu(avg_pct, cpu_history, width, freq_str, throttled))

    # ── Memory + GPU (side-by-side) ──────────────────────────
    ram, swap = sys_collector.collect_memory()
    ram_lines = build_memory_lines(ram, swap)

    # Collect GPU once, reuse for panel + temps
    gpu_data = collect_gpu() if gpu_enabled else None
    if gpu_enabled:
        gpu_lines = build_gpu_lines(gpu_data)
        gpu_title = GPU_NAME[:20] if GPU_AVAILABLE else "GPU"
    else:
        gpu_lines = [Text("Disabled (--no-gpu)", style="dim")]
        gpu_title = "GPU"

    parts.append(build_mem_gpu(ram_lines, gpu_lines, gpu_title))

    # ── Temperatures ─────────────────────────────────────────
    temps = sys_collector.collect_temps_psutil()
    lhm_temps = collect_temps()
    temps.update(lhm_temps)

    # GPU temp from the single collect_gpu() call above
    if gpu_data and gpu_data.get("temp") is not None:
        temps.setdefault("GPU", gpu_data["temp"])

    parts.append(build_temps(temps, lhm_running=bool(lhm_temps)))

    # ── Network ──────────────────────────────────────────────
    rx_now, tx_now = sys_collector.collect_network()
    net_stats = sys_collector.get_network_stats()
    parts.append(build_network(rx_now, tx_now, net_stats))

    # ── Disks ────────────────────────────────────────────────
    sys_collector.collect_disk_io()
    disk_active = collect_disk_active()
    disk_usage = sys_collector.collect_disk_usage(drives)
    drive_map = get_drive_to_disk()
    io_speeds = sys_collector.get_disk_io_speeds()
    parts.append(build_disks(disk_usage, disk_active, io_speeds, drive_map))

    # ── Processes ────────────────────────────────────────────
    procs = sys_collector.collect_processes()
    parts.append(build_procs(procs))

    return Group(*parts)


def run(config: dict):
    """Main loop — initialize collectors and run the Rich Live dashboard."""
    # Set cache TTL from config
    set_cache_ttl(config.get("cache_ttl_seconds", 30))

    # Initialize platform-specific collectors
    init_pdh()

    # Prime psutil counters
    sys_collector.prime()
    time.sleep(1.0)

    refresh = config.get("refresh_seconds", 2.0)

    with Live(
        build_display(config),
        refresh_per_second=1 / refresh,
        screen=True,
        console=_console,
    ) as live:
        while True:
            time.sleep(refresh)
            live.update(build_display(config))
