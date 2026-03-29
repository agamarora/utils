# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A collection of standalone utility scripts for Windows. Each tool lives in its own directory with its own `requirements.txt` and `README.md`. This is **not** a package — there's no shared build system, no monorepo tooling, and no inter-tool dependencies.

## Running the Monitor

```bash
cd monitor && pip install -r requirements.txt && python monitor.py
```

Requires Windows 10/11 and Python 3.10+. Optional: LibreHardwareMonitor with web server on port 8085 for CPU temps and real clock speeds. Optional: NVIDIA GPU for GPU panel.

## Architecture

### monitor/monitor.py (single-file tool)

The monitor is one 590-line Python file with no internal modules. It uses Rich `Live` for full-screen terminal rendering at 2-second intervals.

**Data collection layer** — functions prefixed `collect_*` gather system metrics:
- CPU/memory/network/processes: via `psutil`
- GPU: via `pynvml` (NVIDIA NVML bindings)
- Disk active time %: via Windows PDH API through `ctypes` (reads `\PhysicalDisk(*)\% Disk Time`, same counter as Task Manager)
- CPU temps + real clock speed: via LibreHardwareMonitor's HTTP JSON API at `localhost:8085/data.json`, queried through PowerShell subprocess (cached every `LHM_REFRESH` seconds)
- Drive-to-physical-disk mapping: via `IOCTL_STORAGE_GET_DEVICE_NUMBER` through `ctypes` at startup

**Rendering layer** — functions prefixed `build_*` construct Rich renderables (Panels, Tables, Text). `build_display()` orchestrates all panels into a single `Group`. The CPU panel includes a filled area waveform chart built character-by-character using Unicode block elements.

**Key design choice**: LHM data is fetched via `powershell Invoke-WebRequest` subprocess rather than `requests`/`urllib` to avoid adding a dependency. This is intentional.

## Running luna-monitor

```bash
cd luna-monitor && pip install -e . && luna-monitor
```

On first run, it asks whether to enable the embedded proxy for live usage tracking. Use `luna-monitor --doctor` to change this later.

### luna-monitor/ (pip-installable package)

Modular dashboard with collectors, panels, and an embedded proxy. ~3600 lines across 30 source files. 326 tests.

**Source layout:** `src/luna_monitor/` with subdirectories:
- `collectors/` — data gathering (claude.py, claude_local.py, rate_limit.py, system.py, gpu.py, platform_win.py)
- `panels/` — Rich renderables (claude_status.py, claude_burndown.py, cpu.py, memory.py, gpu.py, disks.py, network.py, temps.py, processes.py)
- `proxy/` — embedded reverse proxy (server.py, lifecycle.py, watchdog.py, cli.py)
- `ui/` — shared chart and color utilities (charts.py, colors.py)

**Key design choices:**
- Proxy runs as a daemon thread with its own asyncio event loop, not blocking the Rich UI
- `auto_decompress=False` in aiohttp ClientSession avoids double-decompression (ZlibError)
- Settings.json modified via read-parse-merge with atomic temp-file-plus-rename writes
- WMI for temps (primary) with LibreHardwareMonitor HTTP fallback
- Config consolidated to `~/.luna-monitor/config.json` (single path)

## Adding a New Tool

Create a new directory with the script, `requirements.txt`, and `README.md`. Add an entry to the root `README.md` under Tools.
