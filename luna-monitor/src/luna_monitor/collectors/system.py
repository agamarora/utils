"""System metrics collection: CPU, memory, network, disk I/O, processes."""

import time
from collections import deque

import psutil

# ── Rolling state ────────────────────────────────────────────

NET_WINDOW = 60  # seconds of rolling network history

_net_rx: deque = deque(maxlen=30)  # ~60s at 2s refresh
_net_tx: deque = deque(maxlen=30)
_net_rx_peak = 0.0
_net_tx_peak = 0.0
_last_net = None

_last_disk_io_per: dict = {}
_disk_io_speeds: dict = {}  # {PhysicalDriveX: (read_bytes/s, write_bytes/s)}

_cpu_history: deque = deque(maxlen=300)  # ~10 min at 2s refresh


def get_cpu_history() -> deque:
    """Return the CPU history deque (for waveform chart)."""
    return _cpu_history


def collect_cpu() -> tuple[float, list[float]]:
    """Collect CPU utilization. Returns (average_pct, per_core_pcts).

    Appends to _cpu_history automatically.
    """
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    avg_pct = sum(per_core) / len(per_core) if per_core else 0.0
    _cpu_history.append(avg_pct)
    return avg_pct, per_core


def collect_cpu_freq() -> tuple[str, float]:
    """Collect CPU frequency. Returns (freq_str, avg_mhz).

    Uses psutil base clock. LHM real clock is in platform_win.
    """
    freq = psutil.cpu_freq()
    if freq:
        avg_mhz = freq.current
        return f"{avg_mhz / 1000:.2f} GHz", avg_mhz
    return "", 0.0


def collect_memory():
    """Collect RAM and swap. Returns (ram, swap) named tuples from psutil."""
    return psutil.virtual_memory(), psutil.swap_memory()


def collect_network() -> tuple[float, float]:
    """Collect network speeds in Mbps. Returns (rx_mbps, tx_mbps).

    Tracks rolling averages and peaks internally.
    """
    global _last_net, _net_rx_peak, _net_tx_peak
    c = psutil.net_io_counters()
    now = time.time()
    if _last_net is None:
        _last_net = (now, c)
        return 0.0, 0.0
    elapsed = now - _last_net[0]
    if elapsed <= 0:
        return 0.0, 0.0
    rx = max(0.0, (c.bytes_recv - _last_net[1].bytes_recv) / elapsed / 1e6 * 8)
    tx = max(0.0, (c.bytes_sent - _last_net[1].bytes_sent) / elapsed / 1e6 * 8)
    _last_net = (now, c)
    _net_rx.append(rx)
    _net_tx.append(tx)
    _net_rx_peak = max(_net_rx_peak, rx)
    _net_tx_peak = max(_net_tx_peak, tx)
    return rx, tx


def get_network_stats() -> dict:
    """Return network rolling stats."""
    return {
        "rx_avg": sum(_net_rx) / len(_net_rx) if _net_rx else 0.0,
        "tx_avg": sum(_net_tx) / len(_net_tx) if _net_tx else 0.0,
        "rx_peak": _net_rx_peak,
        "tx_peak": _net_tx_peak,
    }


def collect_disk_io():
    """Collect per-disk I/O speeds (bytes/s). Updates _disk_io_speeds."""
    global _last_disk_io_per, _disk_io_speeds
    try:
        counters = psutil.disk_io_counters(perdisk=True)
        now = time.time()
        for name, c in counters.items():
            if name in _last_disk_io_per:
                elapsed = now - _last_disk_io_per[name][0]
                if elapsed > 0:
                    prev = _last_disk_io_per[name][1]
                    r = max(0, (c.read_bytes - prev.read_bytes) / elapsed)
                    w = max(0, (c.write_bytes - prev.write_bytes) / elapsed)
                    _disk_io_speeds[name] = (r, w)
            _last_disk_io_per[name] = (now, c)
    except Exception:
        pass


def get_disk_io_speeds() -> dict:
    """Return current disk I/O speeds dict."""
    return _disk_io_speeds


def collect_disk_usage(drives: list[str]) -> list[tuple[str, object]]:
    """Collect disk usage for given drive paths. Returns [(drive, usage), ...]."""
    disks = []
    for d in drives:
        try:
            disks.append((d, psutil.disk_usage(d)))
        except Exception:
            pass
    return disks


def collect_temps_psutil() -> dict:
    """Collect temperatures via psutil (may be empty on Windows without LHM)."""
    temps = {}
    try:
        raw = psutil.sensors_temperatures()
        if raw:
            for name, entries in raw.items():
                for e in entries:
                    temps[e.label or name] = e.current
    except (AttributeError, Exception):
        # AttributeError: sensors_temperatures not available on all platforms
        pass
    return temps


def collect_processes(proc_count: int = 6) -> list[dict]:
    """Collect top processes. Returns list of process info dicts.

    Includes cmdline for Claude process detection.
    """
    skip = {"System Idle Process", "Idle", ""}
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "cmdline"]):
        try:
            if p.info.get("name") not in skip:
                procs.append(p.info)
        except Exception:
            pass
    return procs


def prime():
    """Prime psutil counters. Call once at startup before the main loop."""
    psutil.cpu_percent(percpu=True, interval=None)
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            p.info
        except Exception:
            pass
