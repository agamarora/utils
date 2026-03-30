# Utils

A collection of lightweight, open-source utilities built for daily use on Windows. Each tool lives in its own folder with its own README.

MIT licensed. Contributions welcome.

## Tools

### [monitor/](monitor/) — Terminal System Monitor

A real-time system dashboard that runs entirely in your terminal. Think Task Manager, but minimal, fast, and keyboard-friendly.

**What it shows:**
- CPU utilisation as a rolling waveform (not just a number — you see the trend over time)
- Real-time CPU clock speed via LibreHardwareMonitor (not the static base clock that most tools report)
- Disk active time % (same metric as Task Manager) with per-drive read/write throughput
- GPU utilisation, VRAM, and temperature (NVIDIA)
- RAM and swap usage
- CPU and GPU temperatures
- Network speeds (current, average, peak)
- Top processes split by CPU and RAM usage

**Stack:** Python, psutil, Rich, pynvml, Windows PDH API, LibreHardwareMonitor

```bash
cd monitor && pip install -r requirements.txt && python monitor.py
```

### [luna-monitor/](luna-monitor/) — Claude Code Developer Dashboard

Everything from monitor/ plus live Claude Code usage tracking via an embedded reverse proxy. Built in Rust for fast startup and low resource usage.

**What it shows:**
- Live 5-hour and 7-day usage bars with reset countdown timers and pace indicator
- API health: latency, request count, 429 error tracking
- CPU sparkline with real frequency (via LibreHardwareMonitor auto-detection)
- GPU, memory, disk I/O with active %, network, temperatures, top processes
- `--doctor` interactive setup wizard for proxy configuration

**How usage tracking works:** An embedded reverse proxy captures rate limit headers from Claude Code API responses. No extra API calls needed. If the proxy crashes, Claude Code falls back to the direct API — your workflow is never blocked.

**Stack:** Rust, ratatui, sysinfo, reqwest, nvml-wrapper, Windows PDH API

```bash
cd luna-monitor && cargo build --release
./target/release/luna-monitor.exe
```

## License

MIT — see [LICENSE](LICENSE).
