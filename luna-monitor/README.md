# luna-monitor

Terminal dashboard for Claude Code developers. Tracks your API usage limits, system resources, and proxy health — all in one screen.

![Windows](https://img.shields.io/badge/platform-Windows-blue)
![Rust](https://img.shields.io/badge/language-Rust-orange)

<p align="center">
  <img src="screenshot.png" alt="luna-monitor dashboard" width="720">
</p>

## What it does

- **Claude usage tracking** — 5-hour and 7-day utilization bars with reset timers, pace indicator (rising/steady/falling), ETA to cap, and data freshness indicator. Proxy data is the primary source; API polls every 10 minutes as backup.
- **Embedded proxy** — sits between Claude Code and the API, captures rate limit headers in real time. No polling, no scraping. Proxy data always takes priority over API data for utilization display.
- **System dashboard** — CPU, memory, GPU, disk I/O, temperatures, top processes
- **Auto-detection** — finds LibreHardwareMonitor for real CPU frequency and temps, NVIDIA GPU via NVML, falls back gracefully when either is missing

## Install

### From source (recommended)

Requires [Rust](https://rustup.rs/) (1.70+).

```bash
git clone https://github.com/agamarora/utils.git
cd utils/luna-monitor
cargo build --release
```

The binary is at `target/release/luna-monitor.exe`.

### Pre-built binary

Download `luna-monitor.exe` from [Releases](https://github.com/agamarora/utils/releases) and put it somewhere on your PATH.

## First run

```bash
luna-monitor
```

On first launch it asks whether to enable the embedded proxy for live usage tracking. The proxy rewrites Claude Code's `settings.json` to route API calls through `localhost:9120`, captures rate limit headers, and forwards everything untouched.

If you skip this, luna-monitor still works — it just won't have usage data until you enable the proxy later.

## CLI flags

| Flag | Description |
|---|---|
| `--doctor` | Interactive setup menu — enable/disable proxy, check health, then launch dashboard |
| `--enable-proxy` | Enable proxy and write settings.json (non-interactive) |
| `--disable-proxy` | Remove proxy from settings.json |
| `--no-claude` | Hide Claude usage panels |
| `--no-gpu` | Hide GPU panel |
| `--offline` | No network requests (disables API + proxy health checks) |
| `--refresh <secs>` | Refresh interval (default: 2.0) |
| `--verbose` | Debug logging |
| `--update` | Check for updates |

## Dashboard layout

With Claude enabled (~30 rows):

```
╭ Claude Usage (Max 5x) ─────────────────╮
│ 5h: 12.3% (resets in 3h 42m)          │
│ ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ 7d: 5.1% (resets in 4d 12h)           │
│ ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ Net ↓1.2 Mb/s ↑5 Kb/s  avg ↓1.0 ↑3   │
│ P● C● · → steady · ETA ~2h 15m · updated: just now │
╰────────────────────────────────────────╯
╭ CPU ────────────────╮╭ Temps ──────────╮
│ 14.5% @ 4.21 GHz   ││ CPU: 39°C      │
│ ████████████░░░░░░░ ││ GPU: 42°C      │
╰─────────────────────╯╰────────────────╯
╭ Memory ─────────────╮╭ GPU ────────────╮
│ RAM: 10.5/15.8 GB   ││ RTX 3060 Ti    │
│ Swap: 8.3/12.8 GB   ││ Util: 7%       │
╰─────────────────────╯╰────────────────╯
╭ Disks ─────────────────────────────────╮
│ C:\ 2% active  328/446 GB (74%)       │
│ D:\ 0% active  339/932 GB (36%)       │
╰────────────────────────────────────────╯
╭ Processes ─────────────────────────────╮
│ claude.exe  15.6%    chrome.exe 680 MB │
╰────────────────────────────────────────╯
```

## How the proxy works

luna-monitor includes an embedded reverse proxy (`luna-proxy`) that:

1. Starts on `localhost:9120` (falls back to 9121-9129 if busy)
2. Writes `ANTHROPIC_BASE_URL=http://localhost:9120` to Claude Code's `settings.json`
3. Forwards all requests to `https://api.anthropic.com` untouched
4. Captures `anthropic-ratelimit-*` headers from responses
5. Logs rate limit data to `~/.luna-monitor/rate-limits.jsonl`

The proxy never modifies request or response bodies. If it crashes, Claude Code falls back to the direct API endpoint — your workflow is never blocked.

### Proxy management

```bash
luna-monitor --doctor        # Interactive menu
luna-monitor --enable-proxy  # Enable non-interactively
luna-monitor --disable-proxy # Disable and clean up settings.json
```

## Optional: LibreHardwareMonitor

For real CPU clock speeds and temperature readings, install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) and enable its web server:

1. Open LibreHardwareMonitor
2. Options → Web Server → Enable
3. Keep the default port (8085)

luna-monitor auto-detects LHM at `localhost:8085` — no configuration needed. Without LHM, you get base frequency from sysinfo and a "No sensors" message in the temps panel.

## Optional: NVIDIA GPU

GPU monitoring requires an NVIDIA GPU with drivers installed. The `nvml` library is loaded automatically. If no NVIDIA GPU is found, luna-monitor tries LHM as a fallback. If neither is available, the GPU panel shows "No GPU".

## Troubleshooting

**"Resize terminal (min 60x15)"** — Your terminal is too small. Widen it to at least 60 columns and 15 rows.

**No Claude usage data** — The proxy isn't running or hasn't captured any data yet. Run `luna-monitor --doctor` to check proxy health.

**P● is red** — The proxy isn't active. Run `luna-monitor --enable-proxy` to set it up.

**C● is red** — Can't reach the Claude API. Check your internet connection or re-authenticate with `claude`.

**Disk I/O shows 0 B/s** — PDH counters need one tick cycle to produce data. Wait 2-4 seconds. If a drive only shows capacity (no active %), it means PDH doesn't have a counter for that physical disk.

**Temperatures show "No sensors"** — Install LibreHardwareMonitor and enable its web server on port 8085.

**GPU shows 0°C** — NVML sometimes reports 0°C at idle. This is normal for some GPU models.

**Proxy won't start** — Another process is using ports 9120-9129. Check with `netstat -ano | findstr 9120`.

**settings.json not updating** — luna-monitor writes settings.json atomically (temp file + rename). If Claude Code is mid-write at the same time, retry with `--enable-proxy`.

## Project structure

```
luna-monitor/
├── Cargo.toml              # Workspace root
├── crates/
│   ├── luna-common/        # Shared types, paths, constants
│   └── luna-monitor/       # Dashboard + embedded proxy binary
│       └── src/
│           ├── main.rs
│           ├── app.rs              # Event loop + layout
│           ├── config.rs           # Config load/save
│           ├── platform_win.rs     # PDH disk active %
│           ├── proxy_lifecycle.rs  # Spawn/manage proxy process
│           ├── collectors/         # Data gathering
│           │   ├── system.rs       # CPU, memory, disk, network, processes
│           │   ├── claude.rs       # OAuth + usage API
│           │   ├── claude_local.rs # Local JSONL scanner
│           │   ├── rate_limit.rs   # Proxy rate limit data
│           │   ├── gpu.rs          # NVIDIA NVML + LHM fallback
│           │   └── lhm.rs          # LibreHardwareMonitor HTTP client
│           ├── panels/             # Rich TUI panels
│           │   ├── claude_status.rs # Usage bars + net + status dots + ETA
│           │   ├── cpu.rs
│           │   ├── memory.rs
│           │   ├── gpu.rs
│           │   ├── disks.rs
│           │   ├── network.rs      # Standalone (when Claude disabled)
│           │   ├── temps.rs
│           │   └── processes.rs
│           ├── proxy/              # Embedded reverse proxy
│           │   ├── server.rs       # HTTP proxy + header capture
│           │   ├── jsonl.rs        # Rate limit JSONL logging
│           │   └── health.rs       # Proxy health endpoint
│           └── ui/                 # Charts + color utilities
│               ├── charts.rs
│               └── colors.rs
```

## Requirements

- Windows 10/11
- Terminal with Unicode support (Windows Terminal, VS Code terminal)
- Optional: LibreHardwareMonitor for temps + real CPU frequency
- Optional: NVIDIA GPU for GPU panel

## License

MIT
