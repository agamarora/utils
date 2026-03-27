"""
System Monitor — minimalist terminal cockpit
Vertical bars for CPU cores, panel structure, aggregated network stats.
Requires: psutil, rich, pynvml
Optional: LibreHardwareMonitor running for CPU temps
"""

import psutil
import time
import subprocess
import json
import ctypes
import struct
from ctypes import wintypes
from collections import deque
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box as rich_box
from rich.console import Console, Group

_console = Console()

# ── GPU (NVIDIA via NVML) ────────────────────────────────────
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _GPU_RAW_NAME = pynvml.nvmlDeviceGetName(_GPU_HANDLE)
    GPU_NAME = (_GPU_RAW_NAME.decode() if isinstance(_GPU_RAW_NAME, bytes) else _GPU_RAW_NAME)
    GPU_NAME = GPU_NAME.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False
    _GPU_HANDLE = None

# ── Config ───────────────────────────────────────────────────
REFRESH     = 2.0    # seconds per update
NET_WINDOW  = 60     # seconds of rolling network history
CHART_H     = 7      # height of CPU vertical bar chart (rows)
BAR_W       = 20     # width of horizontal bars
DRIVES      = ["C:\\", "D:\\"]
PROC_COUNT  = 6
LHM_REFRESH = 10     # how often to re-query LibreHardwareMonitor (seconds)

# ── Rolling state ────────────────────────────────────────────
_net_rx      = deque(maxlen=int(NET_WINDOW / REFRESH))
_net_tx      = deque(maxlen=int(NET_WINDOW / REFRESH))
_net_rx_peak = 0.0
_net_tx_peak = 0.0
_last_net    = None

_last_disk_io_per = {}
_disk_io_speeds   = {}   # {PhysicalDriveX: (read_bytes/s, write_bytes/s)}

_cpu_history = deque(maxlen=300)  # ~10 min at 2s refresh

_lhm_cache      = {}
_lhm_last_query = 0.0

BLOCKS = " ▁▂▃▄▅▆▇█"   # 9 levels for smooth waveform


# ── Helpers ──────────────────────────────────────────────────

def _get_drive_to_disk_map() -> dict:
    """Map drive letters to physical disk names via Windows API (instant)."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
    INVALID = wintypes.HANDLE(-1).value
    mapping = {}
    for letter in "CDEFGHIJ":
        path = "\\\\.\\{}:".format(letter)
        h = kernel32.CreateFileW(path, 0, 3, None, 3, 0, None)
        if h != INVALID:
            buf = ctypes.create_string_buffer(12)
            ret = wintypes.DWORD(0)
            ok = kernel32.DeviceIoControl(
                h, IOCTL_STORAGE_GET_DEVICE_NUMBER,
                None, 0, buf, 12, ctypes.byref(ret), None,
            )
            if ok:
                _, dn, _ = struct.unpack("<III", buf.raw)
                mapping[f"{letter}:\\"] = f"PhysicalDrive{dn}"
            kernel32.CloseHandle(h)
    return mapping

DRIVE_TO_DISK = _get_drive_to_disk_map()


# ── Disk active-time % via Windows PDH (like Task Manager) ──
_pdh = ctypes.windll.pdh
_PDH_FMT_DOUBLE = 0x00000200

class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

_pdh_query    = ctypes.c_void_p()
_pdh_counters = {}          # {drive: counter_handle}
_disk_active_pct_pdh = {}   # {drive: %}

def _init_disk_perf():
    if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(_pdh_query)) != 0:
        return
    for drive, phys in DRIVE_TO_DISK.items():
        num = phys.replace("PhysicalDrive", "")
        letter = drive[0]
        path = "\\PhysicalDisk({} {}:)\\% Disk Time".format(num, letter)
        hc = ctypes.c_void_p()
        if _pdh.PdhAddCounterW(_pdh_query, path, 0, ctypes.byref(hc)) == 0:
            _pdh_counters[drive] = hc
    _pdh.PdhCollectQueryData(_pdh_query)   # prime first sample

_init_disk_perf()


def collect_disk_active():
    """Collect disk active-time % via PDH — call once per refresh cycle."""
    if not _pdh_counters:
        return
    _pdh.PdhCollectQueryData(_pdh_query)
    for drive, hc in _pdh_counters.items():
        val = _PDH_FMT_COUNTERVALUE()
        if _pdh.PdhGetFormattedCounterValue(hc, _PDH_FMT_DOUBLE, None, ctypes.byref(val)) == 0:
            _disk_active_pct_pdh[drive] = min(100.0, max(0.0, val.doubleValue))


def _color(pct: float) -> str:
    return "red" if pct >= 85 else ("yellow" if pct >= 60 else "cyan")


def _temp_color(c: float) -> str:
    return "red" if c >= 85 else ("yellow" if c >= 70 else "green")


def _io_color(speed_bps: float) -> str:
    """Color I/O speed by intensity: dim → cyan → yellow → red."""
    mb = speed_bps / 1e6
    if mb >= 100: return "red bold"
    if mb >= 10:  return "yellow bold"
    if mb >= 1:   return "cyan"
    return "dim"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_speed(mbps: float) -> str:
    if mbps >= 1000: return f"{mbps/1000:.1f} Gb/s"
    if mbps >= 1:    return f"{mbps:.1f} Mb/s"
    if mbps >= 0.001: return f"{mbps*1000:.0f} Kb/s"
    return "0 b/s"


def hbar(pct: float, width: int = BAR_W) -> Text:
    filled = int(pct / 100 * width)
    t = Text()
    t.append("█" * filled,          style=_color(pct))
    t.append("░" * (width - filled), style="bright_black")
    return t


def wave_chart(history: deque, height: int = CHART_H) -> list:
    """Filled area chart over time (like Task Manager CPU graph)."""
    width = max(_console.width - 4, 20)   # panel border + padding
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
                line.append("█", style="cyan")
            elif val <= row_bot:
                line.append(" ")
            else:
                frac = (val - row_bot) / row_range
                line.append(BLOCKS[min(8, int(frac * 8))], style="cyan")
        lines.append(line)
    return lines


# ── Data collectors ──────────────────────────────────────────

def collect_network():
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


def collect_disk_io():
    global _last_disk_io_per, _disk_io_speeds
    try:
        counters = psutil.disk_io_counters(perdisk=True)
        now = time.time()
        for name, c in counters.items():
            if name in _last_disk_io_per:
                elapsed = now - _last_disk_io_per[name][0]
                if elapsed > 0:
                    prev = _last_disk_io_per[name][1]
                    r = max(0, (c.read_bytes  - prev.read_bytes)  / elapsed)
                    w = max(0, (c.write_bytes - prev.write_bytes) / elapsed)
                    _disk_io_speeds[name] = (r, w)
            _last_disk_io_per[name] = (now, c)
    except Exception:
        pass


_lhm_clocks = {}   # {"CPU Core #1": 4393.0, ...}  — MHz values from LHM

def _lhm_parse_node(node: dict, out: dict):
    """Recursively walk LHM's data.json tree and collect temperature + clock sensors."""
    val_str = node.get("Value", "")
    name = node.get("Text", "?")
    if "°C" in val_str:
        try:
            out[name] = float(val_str.replace("°C", "").strip())
        except ValueError:
            pass
    if "MHz" in val_str and "CPU Core" in name:
        try:
            _lhm_clocks[name] = float(val_str.replace("MHz", "").strip())
        except ValueError:
            pass
    for child in node.get("Children", []):
        _lhm_parse_node(child, out)


def collect_temps_lhm():
    """Query LibreHardwareMonitor HTTP server (cached every LHM_REFRESH s).
    Enable in LHM: Options → Remote Web Server → Start Web Server (port 8085).
    """
    global _lhm_cache, _lhm_last_query
    if time.time() - _lhm_last_query < LHM_REFRESH:
        return _lhm_cache
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Invoke-WebRequest http://localhost:8085/data.json -TimeoutSec 2 -UseBasicParsing).Content"],
            capture_output=True, text=True, timeout=4,
        )
        if res.returncode == 0 and res.stdout.strip():
            root = json.loads(res.stdout)
            found: dict = {}
            _lhm_parse_node(root, found)
            _lhm_cache = found
    except Exception:
        pass
    _lhm_last_query = time.time()
    return _lhm_cache


def collect_temps():
    temps = {}
    # psutil (may be empty on Intel desktop without LHM)
    try:
        raw = psutil.sensors_temperatures()
        if raw:
            for name, entries in raw.items():
                for e in entries:
                    temps[e.label or name] = e.current
    except Exception:
        pass
    # LibreHardwareMonitor
    temps.update(collect_temps_lhm())
    # GPU via NVML
    if GPU_AVAILABLE and _GPU_HANDLE:
        try:
            t = pynvml.nvmlDeviceGetTemperature(_GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)
            temps.setdefault("GPU", t)
        except Exception:
            pass
    return temps


# ── Panel builders ───────────────────────────────────────────

def panel(content, title: str):
    return Panel(
        content,
        title=f"[bold white]{title}[/bold white]",
        border_style="bright_black",
        box=rich_box.ROUNDED,
        padding=(0, 1),
    )


def build_cpu(avg_pct, freq_str, throttled):
    chart = wave_chart(_cpu_history)
    info = Text()
    info.append(f"Utilisation {avg_pct:.1f}%", style=_color(avg_pct) + " bold")
    if freq_str:
        info.append(f"    Speed {freq_str}", style="dim")
    if throttled:
        info.append("   ⚠ THROTTLING", style="red bold")
    return panel(Group(*chart, info), "CPU")


def _memory_lines(ram, swap):
    lines = []
    bar = hbar(ram.percent)
    row = Text()
    row.append("RAM   ", style="dim")
    row.append_text(bar)
    row.append(f"  {ram.percent:.1f}%", style=_color(ram.percent) + " bold")
    lines.append(row)
    lines.append(Text(f"      {fmt_bytes(ram.used)} / {fmt_bytes(ram.total)}", style="dim"))
    if swap.total > 0:
        sbar = hbar(swap.percent)
        srow = Text()
        srow.append("Swap  ", style="dim")
        srow.append_text(sbar)
        srow.append(f"  {swap.percent:.1f}%", style=_color(swap.percent) + " bold")
        lines.append(srow)
        lines.append(Text(f"      {fmt_bytes(swap.used)} / {fmt_bytes(swap.total)}", style="dim"))
    return lines


def _gpu_lines(gpu_pct, gpu_mem, gpu_temp):
    if not GPU_AVAILABLE or gpu_pct is None:
        return [Text("No GPU data", style="dim")]
    lines = []
    row = Text()
    row.append_text(hbar(gpu_pct))
    row.append(f"  {gpu_pct:.1f}%", style=_color(gpu_pct) + " bold")
    lines.append(row)
    if gpu_mem:
        lines.append(Text(f"VRAM  {fmt_bytes(gpu_mem.used)} / {fmt_bytes(gpu_mem.total)}", style="dim"))
    if gpu_temp is not None:
        lines.append(Text(f"Temp  {gpu_temp}°C", style=_temp_color(gpu_temp) + " bold"))
    return lines


def build_mem_gpu(ram, swap, gpu_pct, gpu_mem, gpu_temp):
    """Build Memory and GPU panels with matched heights."""
    mem = _memory_lines(ram, swap)
    gpu = _gpu_lines(gpu_pct, gpu_mem, gpu_temp)
    # Force both panels to the same height (content lines + 2 for border)
    h = max(len(mem), len(gpu)) + 2
    gpu_title = GPU_NAME[:20] if GPU_AVAILABLE else "GPU"
    side = Table(box=None, padding=0, show_header=False, expand=True)
    side.add_column(ratio=3)
    side.add_column(ratio=2)
    side.add_row(
        Panel(Group(*mem), title=f"[bold white]Memory[/bold white]",
              border_style="bright_black", box=rich_box.ROUNDED, padding=(0, 1), height=h),
        Panel(Group(*gpu), title=f"[bold white]{gpu_title}[/bold white]",
              border_style="bright_black", box=rich_box.ROUNDED, padding=(0, 1), height=h),
    )
    return side


def build_temps(temps):
    lhm_running = bool(collect_temps_lhm())
    cpu_visible = any(k for k in temps if any(x in k.lower() for x in ("package", "tdie", "cpu core")))

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
            content = Text("Enable: LHM → Options → Remote Web Server → Start", style="yellow italic")
        else:
            content = Text("No sensors detected", style="dim")
        return panel(content, "Temps")

    def short_name(name):
        n = name.replace("CPU ", "").replace(" Temperature", "")
        n = n.replace("Core #", "Core ").replace("Package", "Pkg")
        return n[:12]

    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column(width=12, no_wrap=True)
    tbl.add_column(width=6, justify="right")
    tbl.add_column(width=12, no_wrap=True)
    tbl.add_column(width=6, justify="right")

    for i in range(0, len(sensors), 2):
        k1, v1 = sensors[i]
        n1 = Text(short_name(k1), style="dim")
        t1 = Text(f"{v1:.0f}°C", style=_temp_color(v1) + " bold")
        if i + 1 < len(sensors):
            k2, v2 = sensors[i + 1]
            n2 = Text(short_name(k2), style="dim")
            t2 = Text(f"{v2:.0f}°C", style=_temp_color(v2) + " bold")
        else:
            n2, t2 = Text(""), Text("")
        tbl.add_row(n1, t1, n2, t2)

    if not cpu_visible:
        hint = Text()
        if lhm_running:
            hint.append("CPU temp not in sensor set", style="dim italic")
        else:
            hint.append("Enable: LHM → Options → Remote Web Server → Start", style="yellow italic")
        return panel(Group(tbl, hint), "Temps")

    return panel(tbl, "Temps")


def build_network(rx_now, tx_now):
    rx_avg = sum(_net_rx) / len(_net_rx) if _net_rx else 0
    tx_avg = sum(_net_tx) / len(_net_tx) if _net_tx else 0
    dl = Text()
    dl.append("↓  ", style="cyan bold")
    dl.append(f"now {fmt_speed(rx_now):<13}", style="cyan")
    dl.append(f"avg {fmt_speed(rx_avg):<13}", style="dim")
    dl.append(f"peak {fmt_speed(_net_rx_peak)}", style="dim")
    ul = Text()
    ul.append("↑  ", style="magenta bold")
    ul.append(f"now {fmt_speed(tx_now):<13}", style="magenta")
    ul.append(f"avg {fmt_speed(tx_avg):<13}", style="dim")
    ul.append(f"peak {fmt_speed(_net_tx_peak)}", style="dim")
    return panel(Group(dl, ul), "Network")


def build_disks(disks):
    lines = []
    for drive, usage in disks:
        phys_disk = DRIVE_TO_DISK.get(drive)
        active = _disk_active_pct_pdh.get(drive, 0.0)
        r_spd, w_spd = _disk_io_speeds.get(phys_disk, (0, 0)) if phys_disk else (0, 0)

        # Main row: drive label + active time bar + R/W speeds + storage %
        row = Text()
        row.append(f"{drive:<5}", style="bold white")
        row.append_text(hbar(active, width=18))
        row.append(f"  {active:4.1f}%", style=_color(active) + " bold")
        row.append(f"  R {fmt_bytes(r_spd)}/s", style=_io_color(r_spd))
        row.append(f"  W {fmt_bytes(w_spd)}/s", style=_io_color(w_spd))
        row.append(f"  ({usage.percent:.0f}% full)", style="dim")
        lines.append(row)

    return panel(Group(*lines), "Disks")


def _proc_table(procs, highlight: str):
    """Build a process table. highlight='cpu' or 'ram'."""
    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column(ratio=3, no_wrap=True)
    tbl.add_column(width=7, justify="right")
    for p in procs:
        name = (p.get("name") or "")[:24]
        if highlight == "cpu":
            val = p.get("cpu_percent") or 0.0
            style = "red" if val > 30 else ("yellow" if val > 10 else "white")
        else:
            val = p.get("memory_percent") or 0.0
            style = "red" if val > 20 else ("yellow" if val > 10 else "white")
        tbl.add_row(Text(name, style="white"), Text(f"{val:.1f}%", style=style))
    return tbl


def build_procs(all_procs):
    by_cpu = sorted(all_procs, key=lambda x: x.get("cpu_percent") or 0, reverse=True)[:PROC_COUNT]
    by_ram = sorted(all_procs, key=lambda x: x.get("memory_percent") or 0, reverse=True)[:PROC_COUNT]

    side = Table(box=None, padding=0, show_header=False, expand=True)
    side.add_column(ratio=1)
    side.add_column(ratio=1)
    side.add_row(
        panel(_proc_table(by_cpu, "cpu"), "Processes (CPU)"),
        panel(_proc_table(by_ram, "ram"), "Processes (RAM)"),
    )
    return side


# ── Main display ─────────────────────────────────────────────

def build_display():
    # CPU
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    avg_pct  = sum(per_core) / len(per_core)
    _cpu_history.append(avg_pct)
    # Real-time clock from LHM (updated every LHM_REFRESH), fallback to psutil base clock
    if _lhm_clocks:
        avg_mhz = sum(_lhm_clocks.values()) / len(_lhm_clocks)
        freq_str = f"{avg_mhz/1000:.2f} GHz"
    else:
        freq = psutil.cpu_freq()
        avg_mhz = freq.current if freq else 0
        freq_str = f"{avg_mhz/1000:.2f} GHz" if freq else ""
    throttled = bool(avg_mhz > 0 and avg_mhz < 2500 * 0.70)

    # Memory
    ram  = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # GPU
    gpu_pct = gpu_mem = gpu_temp = None
    if GPU_AVAILABLE and _GPU_HANDLE:
        try:
            u = pynvml.nvmlDeviceGetUtilizationRates(_GPU_HANDLE)
            gpu_pct  = u.gpu
            gpu_mem  = pynvml.nvmlDeviceGetMemoryInfo(_GPU_HANDLE)
            gpu_temp = pynvml.nvmlDeviceGetTemperature(_GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            pass

    # Temps
    temps = collect_temps()

    # Network
    rx_now, tx_now = collect_network()

    # Disk
    collect_disk_io()
    collect_disk_active()
    disks = []
    for d in DRIVES:
        try:
            disks.append((d, psutil.disk_usage(d)))
        except Exception:
            pass

    # Processes (filter idle/system noise)
    skip = {"System Idle Process", "Idle", ""}
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            if p.info.get("name") not in skip:
                procs.append(p.info)
        except Exception:
            pass

    return Group(
        build_cpu(avg_pct, freq_str, throttled),
        build_mem_gpu(ram, swap, gpu_pct, gpu_mem, gpu_temp),
        build_temps(temps),
        build_network(rx_now, tx_now),
        build_disks(disks),
        build_procs(procs),
    )


def main():
    # Prime cpu_percent so first real reading is accurate
    psutil.cpu_percent(percpu=True, interval=None)
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try: p.info
        except Exception: pass
    time.sleep(1.2)

    with Live(build_display(), refresh_per_second=1 / REFRESH, screen=True) as live:
        while True:
            time.sleep(REFRESH)
            live.update(build_display())


if __name__ == "__main__":
    main()
