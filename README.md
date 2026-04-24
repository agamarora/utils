# Utils

Open-source tools for developers who live in the terminal. Built for Windows, MIT licensed.

## luna-monitor — The fuel gauge for Claude Code

You're deep in a Claude session. Usage feels high. Are you about to get rate-limited? There's no way to know without leaving your flow.

luna-monitor gives you that answer at a glance. One terminal window shows your 5-hour and 7-day usage limits, how fast you're burning through them, and an ETA to cap. It also shows your CPU, GPU, memory, disk, and temps, because when Claude kicks off a build that pegs your machine, you want to see that too.

<p align="center">
  <img src="luna-monitor/screenshot.png" alt="luna-monitor dashboard" width="720">
</p>

**How it works:** A tiny embedded proxy sits between Claude Code and the Anthropic API. Every response carries rate-limit headers, and the proxy captures them silently. Your requests and responses pass through untouched. The numbers you see are real, live, and straight from Anthropic. The status line tells you when data was last updated: "just now" during active use, "3m ago" when idle.

If the proxy stops, run `luna-monitor --disable-proxy` to restore direct API access.

**Get started:**

```bash
# Download from releases
luna-monitor

# Or build from source
git clone https://github.com/agamarora/utils.git
cd utils/luna-monitor && cargo build --release
```

On first launch it sets up the proxy. That's it. Usage data appears within seconds of your next Claude request.

[Full documentation →](luna-monitor/)

---

## og-squish — 1200×630 OG image optimizer

Your Open Graph image is 2.8 MB and broken at 4K. og-squish resizes to exact 1200×630 and compresses to <300 KB in one command. PNG or JPG — no WebP, because LinkedIn and iMessage still crop or reject WebP OG cards in 2026.

```bash
cd og-squish && npm install
node optimize.mjs /path/to/og-images/
```

[Documentation →](og-squish/)

## monitor — Terminal System Monitor (Python)

The original Python prototype. A real-time system dashboard with CPU waveforms, disk active %, GPU stats, and temperatures. Still works, but luna-monitor is the recommended tool now.

```bash
cd monitor && pip install -r requirements.txt && python monitor.py
```

[Documentation →](monitor/)

## License

MIT — see [LICENSE](LICENSE).
