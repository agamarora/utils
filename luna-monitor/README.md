# luna-monitor

Your system + Claude Code usage in one terminal. The dashboard every Claude Code developer needs running in their second tab.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Windows](https://img.shields.io/badge/platform-Windows-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## One-Command Install

Paste this into your Claude Code terminal and let it handle everything:

```
Clone the luna-monitor tool from https://github.com/agamarora/utils, cd into luna-monitor, install it with pip install -e ., and run luna-monitor to verify it works. If there are any errors, fix them. Show me the output.
```

That's it. Claude Code will clone, install, and verify. You'll see the dashboard in seconds.

## Manual Install

```bash
git clone https://github.com/agamarora/utils.git
cd utils/luna-monitor
pip install -e .
luna-monitor
```

Or if you already have the repo:

```bash
cd luna-monitor
pip install -e .
python -m luna_monitor
```

## What You Get

Two sections in one full-screen terminal dashboard:

**The Soul — Claude Code Usage (top of screen, cyan border)**
- Session (5h) and weekly (7d) usage bars with reset countdown timers
- Per-model breakdown: how much of your Opus vs Sonnet budget you've burned
- Plan tier display (Pro, Max 5x, Max 20x)
- Usage burndown waveform — a chart that tracks your consumption over time and projects when you'll hit your limit. Dynamic title: "~47 min remaining (estimated)"

**The Body — System Monitoring**
- CPU rolling waveform chart (area graph, like Task Manager) + real boost clock speed
- Memory (RAM + swap) and GPU (NVIDIA) side-by-side with matched heights
- Disk active time % (same counter as Task Manager) + per-drive R/W throughput
- Network speeds: current, average, peak (rolling 60s window)
- CPU and GPU temperatures
- Top processes by CPU and RAM — Claude processes highlighted in cyan so you see what Claude Code is doing to your machine

## CLI Flags

```
luna-monitor                    # full dashboard
luna-monitor --no-gpu           # skip GPU panel (no NVIDIA card)
luna-monitor --no-claude        # skip Claude panels (system monitor only)
luna-monitor --offline          # no network requests at all
luna-monitor --refresh 1        # faster refresh (default: 2s)
luna-monitor --version          # print version
```

## How Claude Usage Tracking Works

luna-monitor reads your existing Claude Code OAuth credentials (same approach as [Claude Pulse](https://github.com/mbenhamd/claude-pulse)) to fetch usage data from the Anthropic API.

- Reads from `~/.claude/.credentials.json` — the file Claude Code already created when you logged in
- Tokens stay in memory only, never written to disk
- All requests go through a hardcoded domain allowlist: `api.anthropic.com`, `console.anthropic.com`, `platform.claude.com`
- Redirect blocking prevents token exfiltration
- If the token expires, luna-monitor refreshes it automatically (same flow as Claude Pulse)

**Just run `claude login` first.** If you've used Claude Code, you're already set.

> **API stability note:** The usage API is undocumented. If Anthropic changes it, the Claude panels show "Update luna-monitor" while system panels keep working. The tool never crashes — it degrades gracefully.

## Optional: Get More Data

**GPU monitoring** — install pynvml:
```bash
pip install pynvml
```
Without it, the GPU panel is skipped. No crash, no error.

**CPU temps + real clock speed** — install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor), go to Options > Remote Web Server > Start (port 8085). Without it, temps show a hint and clock speed falls back to the base clock.

## Configuration

Optional. Create `%APPDATA%/luna-monitor/config.json`:

```json
{
  "cache_ttl_seconds": 30,
  "refresh_seconds": 2.0,
  "drives": ["C:\\", "D:\\"]
}
```

Everything has sensible defaults. Most people never need this file.

## Platform

Windows-first. The architecture separates all Windows-specific code (`platform_win.py`) behind a clean abstraction. Linux/macOS stubs exist — real implementations coming in v2.

## 190 Tests

```bash
cd luna-monitor
pip install pytest
python -m pytest tests/ -q
```

Every collector, every panel, every edge case. OAuth flow, burndown prediction, process correlation, graceful degradation — all tested.

## License

MIT
