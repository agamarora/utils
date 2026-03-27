# Monitor

Minimalist terminal system monitor for Windows. Real-time dashboard showing CPU, memory, GPU, disk I/O, network, temperatures, and top processes.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Windows](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **CPU** — rolling waveform chart (area graph over time, like Task Manager) with real-time utilisation % and actual boost clock speed
- **Memory** — RAM and swap usage bars with percentage and byte breakdown
- **GPU** — NVIDIA utilisation, VRAM usage, and temperature (via NVML)
- **Disks** — active time % (same metric as Task Manager), per-drive read/write throughput, storage %
- **Temperatures** — CPU package/core temps and GPU temp
- **Network** — current, average, and peak download/upload speeds (rolling 60s window)
- **Processes** — two side-by-side panels: top 6 by CPU usage, top 6 by RAM usage

## How It Works

Most lightweight monitors on Windows get two things wrong: they report the static base clock instead of the real boost frequency, and they show disk space used instead of disk activity.

This monitor fixes both:

- **CPU clock speed** — Reads real-time per-core MHz from [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)'s HTTP API and averages them. Shows your actual ~4.1 GHz boost, not the 2.5 GHz base clock that `psutil.cpu_freq()` returns.
- **Disk active time %** — Uses the Windows PDH (Performance Data Helper) API via ctypes to read `\PhysicalDisk(*)\% Disk Time`, the same counter Task Manager uses. Drive letters are mapped to physical disks at startup using `IOCTL_STORAGE_GET_DEVICE_NUMBER` — no WMI or PowerShell needed (instant).

## Requirements

- Windows 10/11
- Python 3.10+
- NVIDIA GPU (optional, for GPU panel)
- [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) with web server enabled on port 8085 (optional, for CPU temps and real clock speeds)

## Setup

```bash
pip install -r requirements.txt
```

To enable CPU temperatures and real-time clock speed: open LibreHardwareMonitor, go to Options, Remote Web Server, and click Run.

## Usage

```bash
python monitor.py
```

Refreshes every 2 seconds. The CPU waveform builds up history as it runs — give it a minute to see the trend.

## Configuration

Edit the constants at the top of `monitor.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `REFRESH` | `2.0` | Seconds between updates |
| `CHART_H` | `7` | Height of CPU waveform (rows) |
| `BAR_W` | `20` | Width of horizontal bars |
| `DRIVES` | `["C:\\", "D:\\"]` | Which drives to monitor |
| `PROC_COUNT` | `6` | Number of processes per panel |
| `LHM_REFRESH` | `10` | Seconds between LHM queries |

## Windows Terminal Profile

Add to your Windows Terminal `settings.json` to launch with one click. Only starts LHM if it's not already running, and skips the wait if it is:

```json
{
    "name": "Monitor",
    "commandline": "powershell -NoProfile -Command \"if (-not (Get-Process LibreHardwareMonitor -EA 0)) { Start-Process 'C:\\path\\to\\LibreHardwareMonitor.exe' -WindowStyle Hidden; Start-Sleep 3 }; python path\\to\\monitor.py\"",
    "hidden": false
}
```

## Dependencies

| Package | Purpose |
|---------|---------|
| [psutil](https://github.com/giampaolo/psutil) | CPU, memory, disk, network, process stats |
| [rich](https://github.com/Textualize/rich) | Terminal UI rendering (panels, bars, tables, live refresh) |
| [pynvml](https://github.com/gpuopenanalytics/pynvml) | NVIDIA GPU stats via NVML |

No external binaries required. LibreHardwareMonitor is optional — without it, CPU temps and real clock speed won't be available, but everything else works.
