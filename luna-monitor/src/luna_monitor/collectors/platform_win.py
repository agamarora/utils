"""Windows-specific collectors: PDH disk active time, IOCTL drive mapping, LHM temps.

Guarded by sys.platform check — safe to import on any platform but functions
return empty results on non-Windows.
"""

import json
import subprocess
import sys
import time

# ── State ────────────────────────────────────────────────────
_drive_to_disk: dict = {}
_pdh_query = None
_pdh_counters: dict = {}
_disk_active_pct: dict = {}

_lhm_cache: dict = {}
_lhm_last_query = 0.0
_lhm_clocks: dict = {}  # {"CPU Core #1": 4393.0, ...}

LHM_REFRESH = 10  # seconds between LHM queries


def is_windows() -> bool:
    return sys.platform == "win32"


# ── Drive-to-disk mapping via IOCTL ──────────────────────────

def init_drive_map() -> dict:
    """Map drive letters to physical disk names via Windows API. Returns mapping dict."""
    if not is_windows():
        return {}

    import ctypes
    import struct
    from ctypes import wintypes

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
        path = f"\\\\.\\{letter}:"
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


def get_drive_to_disk() -> dict:
    """Return cached drive-to-disk mapping."""
    global _drive_to_disk
    if not _drive_to_disk and is_windows():
        _drive_to_disk = init_drive_map()
    return _drive_to_disk


# ── PDH disk active time % ───────────────────────────────────

def init_pdh():
    """Initialize PDH counters for disk active time. Call once at startup."""
    global _pdh_query, _pdh_counters
    if not is_windows():
        return

    import ctypes
    from ctypes import wintypes

    pdh = ctypes.windll.pdh
    _pdh_query = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, 0, ctypes.byref(_pdh_query)) != 0:
        _pdh_query = None
        return

    drive_map = get_drive_to_disk()
    for drive, phys in drive_map.items():
        num = phys.replace("PhysicalDrive", "")
        letter = drive[0]
        path = f"\\PhysicalDisk({num} {letter}:)\\% Disk Time"
        hc = ctypes.c_void_p()
        if pdh.PdhAddCounterW(_pdh_query, path, 0, ctypes.byref(hc)) == 0:
            _pdh_counters[drive] = hc

    pdh.PdhCollectQueryData(_pdh_query)  # prime first sample


def collect_disk_active() -> dict:
    """Collect disk active-time % via PDH. Returns {drive: pct}."""
    global _disk_active_pct
    if not is_windows() or _pdh_query is None or not _pdh_counters:
        return _disk_active_pct

    import ctypes
    from ctypes import wintypes

    class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
        _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

    PDH_FMT_DOUBLE = 0x00000200
    pdh = ctypes.windll.pdh

    pdh.PdhCollectQueryData(_pdh_query)
    for drive, hc in _pdh_counters.items():
        val = _PDH_FMT_COUNTERVALUE()
        if pdh.PdhGetFormattedCounterValue(hc, PDH_FMT_DOUBLE, None, ctypes.byref(val)) == 0:
            _disk_active_pct[drive] = min(100.0, max(0.0, val.doubleValue))
    return _disk_active_pct


# ── Temperature collection (WMI → LHM fallback) ─────────────

def _collect_temps_wmi() -> dict:
    """Try WMI for CPU temperature. Returns {label: temp_celsius} or empty."""
    if not is_windows():
        return {}
    try:
        import wmi
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        sensors = w.Sensor()
        temps = {}
        for s in sensors:
            if s.SensorType == "Temperature":
                temps[s.Name] = float(s.Value)
            if s.SensorType == "Clock" and "CPU Core" in s.Name:
                _lhm_clocks[s.Name] = float(s.Value)
        return temps
    except Exception:
        pass

    # Fallback: try MSAcpi_ThermalZoneTemperature (requires admin, less reliable)
    try:
        import wmi
        w = wmi.WMI(namespace="root\\wmi")
        zones = w.MSAcpi_ThermalZoneTemperature()
        temps = {}
        for i, z in enumerate(zones):
            # WMI returns temp in tenths of Kelvin
            celsius = (z.CurrentTemperature / 10.0) - 273.15
            if 0 < celsius < 120:
                temps[f"Thermal Zone {i}"] = round(celsius, 1)
        return temps
    except Exception:
        return {}


def _lhm_parse_node(node: dict, temps: dict):
    """Recursively walk LHM data.json and collect temp + clock sensors."""
    val_str = node.get("Value", "")
    name = node.get("Text", "?")
    if "°C" in val_str:
        try:
            temps[name] = float(val_str.replace("°C", "").strip())
        except ValueError:
            pass
    if "MHz" in val_str and "CPU Core" in name:
        try:
            _lhm_clocks[name] = float(val_str.replace("MHz", "").strip())
        except ValueError:
            pass
    for child in node.get("Children", []):
        _lhm_parse_node(child, temps)


def _collect_temps_lhm() -> dict:
    """Query LibreHardwareMonitor HTTP server. Returns temps or empty."""
    if not is_windows():
        return {}
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Invoke-WebRequest http://localhost:8085/data.json "
             "-TimeoutSec 2 -UseBasicParsing).Content"],
            capture_output=True, text=True, timeout=4,
        )
        if res.returncode == 0 and res.stdout.strip():
            root = json.loads(res.stdout)
            found: dict = {}
            _lhm_clocks.clear()
            _lhm_parse_node(root, found)
            return found
    except Exception:
        pass
    return {}


def collect_temps() -> dict:
    """Collect CPU temps: try WMI first, fall back to LHM HTTP server.

    Cached every LHM_REFRESH seconds regardless of source.
    """
    global _lhm_cache, _lhm_last_query
    if time.time() - _lhm_last_query < LHM_REFRESH:
        return _lhm_cache

    # Try WMI first (no external dependency, no admin)
    temps = _collect_temps_wmi()
    if temps:
        _lhm_cache = temps
        _lhm_last_query = time.time()
        return _lhm_cache

    # Fall back to LHM HTTP server
    temps = _collect_temps_lhm()
    if temps:
        _lhm_cache = temps

    _lhm_last_query = time.time()
    return _lhm_cache


def get_clocks() -> dict:
    """Return clock speed data (populated by collect_temps)."""
    return _lhm_clocks


def get_freq_str() -> tuple[str, float]:
    """Get formatted CPU frequency from LHM clocks. Returns (freq_str, avg_mhz)."""
    if _lhm_clocks:
        avg_mhz = sum(_lhm_clocks.values()) / len(_lhm_clocks)
        return f"{avg_mhz / 1000:.2f} GHz", avg_mhz
    return "", 0.0
