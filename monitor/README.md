# Monitor

Minimalist terminal system monitor for Windows. Real-time dashboard showing CPU, memory, GPU, disk I/O, network, temperatures, and top processes.

![Python](https://img.shields.io/badge/python-3.10+-blue)

## Features

- **CPU** — rolling waveform chart with real-time utilisation % and clock speed (via LibreHardwareMonitor)
- **Memory** — RAM and swap usage bars
- **GPU** — NVIDIA utilisation, VRAM, and temperature (via NVML)
- **Disks** — active time % (like Task Manager), read/write throughput per drive, storage %
- **Temperatures** — CPU package/core temps, GPU temp (via LibreHardwareMonitor)
- **Network** — current, average, and peak download/upload speeds
- **Processes** — two panels: top 6 by CPU, top 6 by RAM

## Requirements

- Windows 10/11
- Python 3.10+
- [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) with web server enabled (port 8085) for CPU temps and real-time clock speeds

## Setup

```bash
pip install -r requirements.txt
```

Enable LHM web server: LHM → Options → Remote Web Server → Run.

## Usage

```bash
python monitor.py
```

Refreshes every 2 seconds. Run as administrator for full sensor access.

## Windows Terminal Profile

Add to your Windows Terminal settings to launch with one click:

```json
{
    "name": "Monitor",
    "commandline": "powershell -NoProfile -Command \"if (-not (Get-Process LibreHardwareMonitor -EA 0)) { Start-Process 'C:\\path\\to\\LibreHardwareMonitor.exe' -WindowStyle Hidden; Start-Sleep 3 }; python path\\to\\monitor.py\"",
    "hidden": false
}
```
