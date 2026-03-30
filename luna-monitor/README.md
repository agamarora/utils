# luna-monitor

**Know exactly how much Claude you have left.**

If you're a Claude Code developer, you've hit this: you're deep in a session, usage feels high, and you have no idea if you're about to get rate-limited. You alt-tab to check... somewhere? There's no dashboard. There's no fuel gauge. You're flying blind.

luna-monitor fixes that. One terminal window shows you everything: how much of your 5-hour and 7-day limits you've burned, how fast you're burning it, when it resets, and an ETA to cap. Plus your CPU, GPU, memory, disk, and temps alongside it, because when Claude kicks off a build that pegs your machine, you want to see that too.

![Windows](https://img.shields.io/badge/platform-Windows-blue)
![Rust](https://img.shields.io/badge/language-Rust-orange)

<p align="center">
  <img src="screenshot.png" alt="luna-monitor dashboard" width="720">
</p>

## How it works

luna-monitor ships with a tiny embedded proxy that sits between Claude Code and the Anthropic API. Every response that comes back carries rate-limit headers, and the proxy captures them silently. Your requests and responses are forwarded untouched.

This means the usage numbers you see are real, live, straight from Anthropic's servers. Not scraped. Not estimated. Not stale. The status line tells you exactly when the data was last updated: "just now" during active use, "3m ago" when you've been idle.

If the proxy stops, run `luna-monitor --disable-proxy` to restore direct API access.

## Get started

### Download

Grab `luna-monitor.exe` from [Releases](https://github.com/agamarora/utils/releases) and put it on your PATH.

### Or build from source

```bash
git clone https://github.com/agamarora/utils.git
cd utils/luna-monitor
cargo build --release
```

### Run it

```bash
luna-monitor
```

On first launch, it asks to set up the proxy. Say yes. That's it. You'll see your usage data within seconds of your next Claude request.

## What you see

**Usage bars** — Your 5-hour and 7-day utilization with reset countdowns. These are Anthropic's actual rate-limit windows.

**Pace** — Are you speeding up (↑ rising), slowing down (↓ falling), or cruising (→ steady)?

**ETA to cap** — At your current pace, how long until you hit the limit. Gives you time to plan: wrap up the big task now or save it for after the reset.

**Freshness** — "updated: just now" means live proxy data. "updated: 5m ago" means you've been idle, the numbers are from your last session. You always know if what you're looking at is current.

**P● C●** — Green dots = proxy running, Claude API reachable. Red = something needs attention.

**System panels** — CPU load, real clock speed, memory, GPU utilization, disk I/O with active %, temperatures. When Claude kicks off `cargo build` or `npm install`, you see the impact instantly.

## CLI options

```bash
luna-monitor                 # Launch dashboard
luna-monitor --doctor        # Interactive setup (proxy, health checks)
luna-monitor --enable-proxy  # Enable proxy (non-interactive)
luna-monitor --disable-proxy # Remove proxy from settings.json
luna-monitor --no-claude     # System monitoring only
luna-monitor --no-gpu        # Hide GPU panel
luna-monitor --update        # Check for updates
```

## Optional extras

**LibreHardwareMonitor** — For real CPU clock speeds and temperature readings. Install [LHM](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor), enable its web server (Options → Web Server, port 8085). luna-monitor finds it automatically.

**NVIDIA GPU** — Detected via NVML if you have NVIDIA drivers installed. Falls back to LHM if available. No config needed.

## Troubleshooting

| Problem | Fix |
|---|---|
| No usage data | Proxy isn't running. Run `luna-monitor --doctor` |
| P● is red | Run `luna-monitor --enable-proxy` |
| C● is red | Check internet or re-auth with `claude` |
| "Resize terminal" | Make your terminal at least 60 columns wide |
| Temps show "No sensors" | Install LibreHardwareMonitor |
| Proxy won't start | Port 9120 is busy. Check `netstat -ano \| findstr 9120` |

## Requirements

- Windows 10/11
- Terminal with Unicode support (Windows Terminal, VS Code terminal)

## License

MIT
