# Roadmap

## v1 — claude-dev-buddy (Modular Cockpit)

Build a full-screen Rich terminal dashboard combining Claude Code usage tracking with system monitoring. Claude usage is the soul; system metrics are the supporting context.

### Milestone 1: Scaffold
- [ ] Create `claude-dev-buddy/` package structure (pyproject.toml, src layout, __main__.py)
- [ ] Set up entry point: `claude-dev-buddy = "claude_dev_buddy.__main__:main"`
- [ ] Define shared types/interfaces for collectors and panels

### Milestone 2: Port System Panels
- [ ] Port CPU waveform panel from monitor.py (collectors/system.py + panels/cpu.py)
- [ ] Port memory panel (panels/memory.py)
- [ ] Port GPU panel with optional pynvml (collectors/gpu.py + panels/gpu.py)
- [ ] Port disk I/O panel, Windows PDH behind platform abstraction (collectors/platform_win.py + panels/disks.py)
- [ ] Port network panel (panels/network.py)
- [ ] Port temperature panel (panels/temps.py)
- [ ] Port process panel (panels/processes.py)
- [ ] Extract shared rendering utils (ui/charts.py, ui/colors.py)

### Milestone 3: Claude Usage (the soul)
- [ ] Build OAuth token reader (~/.claude/.credentials.json)
- [ ] Implement token refresh flow (POST console.anthropic.com/v1/oauth/token)
- [ ] Build usage API collector (GET api.anthropic.com/api/oauth/usage) with 60s cache
- [ ] Build Claude Status panel — session %, weekly %, model, reset timers
- [ ] Build Claude Burndown panel — usage waveform with linear regression projection
- [ ] Handle cold start (< 10 data points: "Collecting data...")
- [ ] Handle edge cases (flat usage: "Pace: sustainable", usage reset: clear deque)

### Milestone 4: Process Correlation
- [ ] Detect Claude-related processes (claude, node with @anthropic args)
- [ ] Highlight Claude processes in the process panel with distinct color

### Milestone 5: Compositor + Config
- [ ] Wire all panels into app.py compositor (Rich Group, Claude panels on top)
- [ ] Implement responsive layout (collapse side-by-side panels at <80 cols)
- [ ] Add config file support (~/.config/claude-dev-buddy/config.json)
- [ ] Graceful degradation: no GPU, no Claude API, no LHM

### Milestone 6: Ship
- [ ] Screenshot for README (the marketing)
- [ ] Write README with install instructions, feature list, screenshot
- [ ] Publish to PyPI
- [ ] GitHub Actions CI (lint, test, publish on tag)
- [ ] Tag v1.0.0

## v2 — Future Ideas (not committed)
- Cross-platform support (Linux, macOS) via platform_posix.py
- Theming / color customization
- Panel plugin system (entry_points for third-party panels)
- Read Claude session JSONL for model/token data without Pulse dependency
- Git awareness (branch, uncommitted changes, recent commits)
- Keyboard shortcuts (toggle panels, change refresh rate)
