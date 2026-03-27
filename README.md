# Utils

A collection of lightweight, open-source utility scripts built for daily use on Windows. Each tool lives in its own folder with its own README, dependencies, and setup instructions.

Built with Python. MIT licensed. Contributions welcome.

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

**Why it exists:** Windows Task Manager is fine, but it's a mouse-heavy GUI that takes up a full window. This fits in a terminal tab, refreshes every 2 seconds, and shows everything at a glance. It also pulls real CPU clock speeds and accurate disk I/O metrics that most lightweight monitors miss.

**Stack:** Python, psutil, Rich, pynvml, Windows PDH API, LibreHardwareMonitor

```bash
cd monitor && pip install -r requirements.txt && python monitor.py
```

## Adding New Tools

Each tool gets its own directory with:
- The script(s)
- A `requirements.txt` (if it has Python deps)
- A `README.md` explaining what it does and how to use it

## License

MIT — see [LICENSE](LICENSE).
