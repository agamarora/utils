# luna-monitor

Your system + Claude Code usage in one terminal. The dashboard every Claude Code developer needs running in their second tab.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Windows](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## Install

**pip (recommended):**
```bash
pip install luna-monitor
luna-monitor
```

**Standalone .exe (no Python needed):**
Download `luna-monitor.exe` from the [latest release](https://github.com/agamarora/utils/releases/latest) and run it.

**Claude Code one-liner:**
Paste this into your Claude Code terminal:
```
Clone the luna-monitor tool from https://github.com/agamarora/utils, cd into luna-monitor, install it with pip install luna-monitor, and run luna-monitor to verify it works. If there are any errors, fix them. Show me the output.
```

**From source:**
```bash
git clone https://github.com/agamarora/utils.git
cd utils/luna-monitor
pip install --user -e .
luna-monitor
```

> **Windows note:** If `luna-monitor` isn't found after install, use `python -m luna_monitor` instead.

## What You Get

Two sections in one full-screen terminal dashboard:

**The Soul — Claude Code Usage (top of screen, cyan border)**
- Live session (5h) and weekly (7d) usage bars with reset countdown timers
- Usage burndown waveform — tracks consumption over time, projects when you'll hit your limit
- Plan tier display (Pro, Max 5x, Max 20x)
- API health: latency, request count, 429 error tracking
- Proxy status indicator ("via proxy" / "via API")

**The Body — System Monitoring**
- CPU rolling waveform chart (area graph, like Task Manager) + real boost clock speed
- Memory (RAM + swap) and GPU (NVIDIA) side-by-side with matched heights
- Disk active time % (same counter as Task Manager) + per-drive R/W throughput
- Network speeds: current, average, peak (rolling 60s window)
- CPU and GPU temperatures (WMI or LibreHardwareMonitor)
- Top processes by CPU and RAM — Claude processes highlighted in cyan

## Live Usage Tracking via Proxy

luna-monitor includes an embedded reverse proxy that captures real-time usage data from Claude Code API responses. This is how you get accurate session/weekly utilization without relying on the broken usage API endpoint.

**How it works:**
1. On first run, luna-monitor asks if you want to enable live usage tracking
2. If yes, it starts a local proxy on port 9120 and sets `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`
3. All Claude Code API traffic flows through the proxy — luna-monitor reads rate limit headers from responses
4. Headers captured: `anthropic-ratelimit-unified-5h-utilization`, `anthropic-ratelimit-unified-7d-utilization`
5. On exit (Ctrl+C, signals, crashes), everything is cleaned up automatically

**Safety layers:**
- Crash recovery: detects stale config from previous crashes and cleans up on next start
- Watchdog: daemon thread monitors proxy health, auto-restarts on failure (3-failure threshold)
- Lockfile: PID-based lockfile prevents duplicate proxy instances
- Signal handlers: atexit + SIGTERM + SIGINT ensure cleanup
- Settings.json backup: original file backed up before modification, restored on cleanup

**The proxy is fully optional.** Without it, luna-monitor works as a system monitor. The proxy just adds live Claude usage data.

## CLI Flags

```
luna-monitor                    # full dashboard (prompts for proxy on first run)
luna-monitor --doctor           # interactive setup: enable/disable proxy or reset
luna-monitor --enable-proxy     # enable proxy without interactive prompt
luna-monitor --disable-proxy    # disable proxy, restore settings.json
luna-monitor --no-gpu           # skip GPU panel (no NVIDIA card)
luna-monitor --no-claude        # skip Claude panels (system monitor only)
luna-monitor --offline          # no network requests at all
luna-monitor --refresh 1        # faster refresh (default: 2s)
luna-monitor --version          # print version
```

### --doctor

Interactive setup wizard with three options:
1. **Enable proxy** — route Claude Code through luna-monitor for live usage %
2. **Disable proxy** — direct Claude Code, keep luna-monitor for system metrics
3. **Reset everything** — remove all luna-monitor config, restore vanilla Claude Code

## How Claude Usage Tracking Works

**With proxy (recommended):** luna-monitor reads rate limit headers directly from Claude Code API responses. No extra API calls needed — the data comes from headers Anthropic already sends on every completion request.

**Without proxy (fallback):** luna-monitor reads your existing Claude Code OAuth credentials to fetch usage data from the Anthropic API. Note: this endpoint has aggressive rate limiting (known issue with 7+ open GitHub issues).

- Reads from `~/.claude/.credentials.json` — the file Claude Code already created when you logged in
- Tokens stay in memory only, never written to disk
- All requests go through a hardcoded domain allowlist
- If the token expires, luna-monitor refreshes it automatically

**Just run `claude login` first.** If you've used Claude Code, you're already set.

> **API stability note:** If Anthropic changes their API, the Claude panels degrade gracefully while system panels keep working. The tool never crashes.

## Optional: Get More Data

**GPU monitoring** — install pynvml:
```bash
pip install pynvml
```
Without it, the GPU panel is skipped. No crash, no error.

**CPU temps** — luna-monitor tries these sources in order:
1. **WMI** (via `pip install wmi`) — queries Windows Management Instrumentation directly
2. **LibreHardwareMonitor** — if running with web server on port 8085
3. Falls back to "N/A" gracefully if neither is available

## Configuration

Optional. Create `~/.luna-monitor/config.json`:

```json
{
  "proxy_enabled": true,
  "proxy_port": 9120,
  "cache_ttl_seconds": 30,
  "refresh_seconds": 2.0,
  "drives": ["C:\\", "D:\\"]
}
```

Everything has sensible defaults. Most people never need this file.

## Add as a Terminal Profile (always one click away)

### Windows Terminal

Open Settings (Ctrl+,) > Add a new profile > New empty profile:

- **Name:** Luna Monitor
- **Command line:** `python -m luna_monitor`
- **Starting directory:** `%USERPROFILE%`
- **Icon:** pick any moon/monitor emoji or leave default

Now luna-monitor is always one click away in your terminal dropdown.

### Launcher Scripts (optional)

If you want a simple shortcut you can double-click or pin to taskbar:

**PowerShell (`luna.ps1`):**
```powershell
# Save this as luna.ps1 anywhere, right-click > Run with PowerShell
python -m luna_monitor
```

**Bash (`luna.sh`):**
```bash
#!/bin/bash
# Save this as luna.sh, chmod +x luna.sh
python -m luna_monitor "$@"
```

**Windows Batch (`luna.bat`):**
```batch
@echo off
python -m luna_monitor %*
```

Drop any of these in a folder on your PATH and you can just type `luna` from anywhere.

## Platform

Windows-first. The architecture separates all Windows-specific code (`platform_win.py`) behind a clean abstraction. Linux/macOS stubs exist — real implementations welcome as PRs.

## 327 Tests

```bash
cd luna-monitor
pip install pytest
python -m pytest tests/ -q
```

Every collector, every panel, every edge case. OAuth flow, burndown prediction, proxy lifecycle, crash recovery, watchdog restart, process correlation, graceful degradation — all tested.

## License

MIT
