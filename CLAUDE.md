# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A collection of standalone utilities for Windows. Each tool lives in its own directory with its own README. This is **not** a monorepo — there's no shared build system and no inter-tool dependencies.

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

### luna-monitor/ (Rust workspace)

Terminal dashboard for Claude Code developers. Rust workspace with 2 crates, 63 tests.

```bash
cd luna-monitor && cargo build --release
./target/release/luna-monitor.exe
```

**Workspace layout:** `crates/` with:
- `luna-common/` — shared types (UsageData, ProxyHealth, RateLimitEntry), path constants
- `luna-monitor/` — dashboard binary + embedded proxy (ratatui TUI, collectors, panels, proxy)

**Collectors:** system.rs (sysinfo), claude.rs (OAuth + usage API), claude_local.rs (JSONL scanner), rate_limit.rs (proxy data), gpu.rs (nvml + LHM fallback), lhm.rs (LibreHardwareMonitor HTTP auto-detection)

**Panels:** claude_status (5h/7d bars + pace + ETA + net speeds + P●/C● status dots + freshness indicator), cpu (sparkline + hbar), memory, gpu, disks (I/O + active %), network (standalone when Claude disabled), temps, processes

**Key design choices:**
- Proxy data is the authority for utilization; API demoted to 10-min background backup for per-model breakdown
- Proxy runs as a separate process, managed by proxy_lifecycle.rs (spawn, PID file, crash recovery)
- LHM auto-detected at localhost:8085, cached 10s, graceful fallback
- PDH disk active % via Windows FFI (platform_win.rs)
- Settings.json modified via atomic temp-file-plus-rename writes
- Config at `~/.luna-monitor/config.json`

## Adding a New Tool

Create a new directory with the tool and a `README.md`. Add an entry to the root `README.md` under Tools.
