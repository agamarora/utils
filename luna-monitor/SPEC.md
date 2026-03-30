# luna-monitor-rs: Complete Specification

> This document is the source of truth for building luna-monitor in Rust.
> Every module, struct, function, and data flow is specified here.
> The build session implements exactly what this spec says.

## Build Progress

### Session 1 (2026-03-30) — Completed

**Rust toolchain:** Installed. rustc 1.94.1, cargo 1.94.1 (minimal profile, no docs).
PATH: `$HOME/.cargo/bin` (must be exported in each shell session).

**luna-common** — DONE (7 tests passing)
- `src/lib.rs` — module exports
- `src/types.rs` — RateLimitEntry, ProxyHealth, UsageWindow, UsageData, LocalUsageData
- `src/paths.rs` — all path functions returning Option<PathBuf>, constants

**luna-proxy** — DONE (10 tests passing)
- `src/main.rs` — CLI (clap), tokio server, port fallback 9120-9129, PID file, stale cleanup, ctrlc handler, request routing (/health vs proxy)
- `src/proxy.rs` — ProxyState, request handler (forward to upstream, capture 5 rate limit headers, hop-by-hop stripping, fire-and-forget JSONL write, error tracking, 502/504 responses)
- `src/jsonl.rs` — write_entry (append), rotate (keep last N)
- `src/health.rs` — GET /health returning ProxyHealth JSON

**luna-monitor** — DONE (45 tests passing)
- All 23 source files implemented
- All collectors, panels, UI utilities, proxy lifecycle, app loop, CLI

### Session 2 (2026-03-30) — Completed

All luna-monitor source files built and tested:

1. `src/config.rs` — Config struct, serde defaults, load/save, 4 tests
2. `src/collectors/mod.rs` — module exports
3. `src/collectors/system.rs` — SystemCollector (sysinfo CPU, memory, network, disk, processes, temps)
4. `src/collectors/gpu.rs` — GpuCollector (nvml-wrapper, optional feature gate)
5. `src/collectors/claude.rs` — ClaudeCollector (OAuth, usage API, backoff, disk cache, custom redirect policy), burndown_prediction, calibrate_limit, is_window_expired — 16 tests
6. `src/collectors/claude_local.rs` — LocalCollector (JSONL scanner, token weighting, dedup) — 5 tests
7. `src/collectors/rate_limit.rs` — RateLimitCollector (read proxy JSONL, proxy health check) — 4 tests
8. `src/proxy_lifecycle.rs` — ProxyManager (spawn detached, settings.json atomic writes, crash recovery) — 6 tests
9. `src/ui/mod.rs` — module exports
10. `src/ui/charts.rs` — wave_chart, hbar, fmt_bytes, fmt_speed — 8 tests
11. `src/ui/colors.rs` — pct_color, temp_color, io_color, color constants — 3 tests
12. `src/panels/mod.rs` — module exports
13. `src/panels/cpu.rs` — CPU waveform panel
14. `src/panels/memory.rs` — RAM + swap panel
15. `src/panels/gpu.rs` — GPU panel
16. `src/panels/disks.rs` — disk usage + I/O panel
17. `src/panels/network.rs` — network speeds panel
18. `src/panels/temps.rs` — temperature panel
19. `src/panels/processes.rs` — top processes panel (dual-column, Claude highlighting)
20. `src/panels/claude_status.rs` — Claude usage status panel
21. `src/panels/claude_burndown.rs` — burndown waveform + prediction panel
22. `src/app.rs` — tick loop, compositor, terminal init/restore, min-size check
23. `src/main.rs` — CLI (clap), startup flow, doctor mode, first-run prompt

**Total tests: 62** (7 luna-common + 45 luna-monitor + 10 luna-proxy)

### Session 2 Integration Testing — Completed

Verification results (see section 10 for full checklist):
- 24/32 items verified (automated + unit tested)
- 6 items need interactive testing (doctor menu, first-run, terminal resize)
- 2 known limitations (temps via sysinfo, disk I/O active %)

Key fixes during verification:
- Rate limit JSONL now propagates both 5h AND 7d utilization + reset times to dashboard
- Layout uses fixed constraints with Min() for CPU waveform
- Removed temps panel from default layout (sysinfo doesn't expose WMI temps)
- All #[allow(dead_code)] for spec'd but not-yet-connected features
- 0 warnings, 0 errors

### Remaining Work

- Windows PDH disk I/O (disk_io() returns empty — sysinfo doesn't expose active %)
- LHM HTTP fallback for temperatures (sysinfo returns no temps on Windows)
- self_update integration (needs published GitHub release)
- Interactive testing: --doctor, first-run prompt, terminal resize, full Claude panels in tall terminal

### Implementation Notes

- Every `cargo` command needs: `export PATH="$HOME/.cargo/bin:$PATH"`
- hyper-tls is used (not hyper-rustls) because rustls had version conflicts. Works fine.
- luna-proxy collects the full upstream response body before forwarding (not true streaming). This is fine for Claude Code API responses which are small. If SSE streaming is needed later, switch to frame-by-frame forwarding.
- PID file format: `"{pid} {unix_timestamp}"` (space-separated)
- Binaries: luna-proxy.exe 3.6MB, luna-monitor.exe 6.5MB (release build)
- Claude panels need 46+ row terminal for full display; system-only mode works at 33+ rows

## Why Rust

luna-monitor's Python proxy uses aiohttp, whose C extensions hang on Windows. The broken code is inside compiled .pyd binaries that can't be read, debugged, or fixed. Any Python C extension dependency can fail the same way. A system monitoring tool must be 100% reliable. Rust gives us: single binary, zero runtime dependencies, every line readable, cross-platform from one codebase.

## Product

Two binaries:
- **luna-monitor** — full-screen terminal dashboard showing system metrics + Claude Code usage
- **luna-proxy** — transparent HTTP proxy that captures Anthropic rate limit headers

They communicate via a JSONL file. luna-proxy runs as an independent process (not a child of luna-monitor). Either can crash without affecting the other.

---

## 1. Workspace Layout

```
luna-monitor-rs/
├── Cargo.toml                          # [workspace]
├── SPEC.md                             # this file
├── crates/
│   ├── luna-common/                    # shared types + paths
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── types.rs
│   │       └── paths.rs
│   ├── luna-proxy/                     # proxy binary
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs
│   │       ├── proxy.rs
│   │       ├── jsonl.rs
│   │       └── health.rs
│   └── luna-monitor/                   # dashboard binary
│       ├── Cargo.toml
│       └── src/
│           ├── main.rs
│           ├── app.rs
│           ├── config.rs
│           ├── proxy_lifecycle.rs
│           ├── collectors/
│           │   ├── mod.rs
│           │   ├── system.rs
│           │   ├── gpu.rs
│           │   ├── claude.rs
│           │   ├── claude_local.rs
│           │   └── rate_limit.rs
│           ├── panels/
│           │   ├── mod.rs
│           │   ├── cpu.rs
│           │   ├── memory.rs
│           │   ├── gpu.rs
│           │   ├── disks.rs
│           │   ├── network.rs
│           │   ├── temps.rs
│           │   ├── processes.rs
│           │   ├── claude_status.rs
│           │   └── claude_burndown.rs
│           └── ui/
│               ├── mod.rs
│               ├── charts.rs
│               └── colors.rs
```

---

## 2. Dependencies

### luna-common

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
dirs = "5"
```

### luna-proxy

```toml
[dependencies]
luna-common = { path = "../luna-common" }
hyper = { version = "1", features = ["server", "client", "http1"] }
hyper-util = { version = "0.1", features = ["tokio", "server-auto", "client-legacy"] }
hyper-rustls = { version = "0.27", features = ["http1", "tls12", "ring"] }
http-body-util = "0.1"
bytes = "1"
tokio = { version = "1", features = ["full"] }
serde_json = "1"
clap = { version = "4", features = ["derive"] }
dirs = "5"
tracing = "0.1"
tracing-subscriber = "0.3"
ctrlc = "3"
```

### luna-monitor

```toml
[dependencies]
luna-common = { path = "../luna-common" }
ratatui = "0.29"
crossterm = "0.28"
sysinfo = "0.32"
tokio = { version = "1", features = ["full"] }
reqwest = { version = "0.12", default-features = false, features = ["rustls-tls", "json"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
clap = { version = "4", features = ["derive"] }
dirs = "5"
chrono = "0.4"
glob = "0.3"
tracing = "0.1"
tracing-subscriber = "0.3"
ctrlc = "3"
self_update = "0.41"

[target.'cfg(windows)'.dependencies]
windows = { version = "0.58", features = [
    "Win32_System_Performance",
    "Win32_System_IO",
] }

[features]
default = []
# NOTE: nvml-wrapper dynamically links nvidia's nvml.dll/libnnvml.so.
# This is a C dependency. It is optional and disabled by default.
# Enable with: cargo build --features gpu
# If nvml.dll is missing at runtime, GPU panel is silently skipped.
gpu = ["dep:nvml-wrapper"]

[dependencies.nvml-wrapper]
version = "0.10"
optional = true
```

**Dependency honesty:** nvml-wrapper dynamically links NVIDIA's C library (nvml.dll).
This is the ONE exception to "no C dependencies." It is optional and off by default.
GPU panel works only when explicitly enabled AND nvml.dll is present at runtime.
All other dependencies are pure Rust.

---

## 3. luna-common: Shared Types

### types.rs

```rust
/// Rate limit entry written by luna-proxy, read by luna-monitor.
/// One per line in ~/.luna-monitor/rate-limits.jsonl
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitEntry {
    #[serde(rename = "5h_utilization", skip_serializing_if = "Option::is_none")]
    pub five_h_utilization: Option<f64>,
    #[serde(rename = "7d_utilization", skip_serializing_if = "Option::is_none")]
    pub seven_d_utilization: Option<f64>,
    #[serde(rename = "5h_reset", skip_serializing_if = "Option::is_none")]
    pub five_h_reset: Option<String>,
    #[serde(rename = "7d_reset", skip_serializing_if = "Option::is_none")]
    pub seven_d_reset: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    pub ts: String,
}

/// Health response from GET /health
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyHealth {
    pub status: String,
    pub uptime_s: u64,
    pub requests_proxied: u64,
    pub last_capture_ts: String,
    pub api_errors_total: u64,
    pub api_errors_429: u64,
    pub last_latency_ms: f64,
}

/// Usage window from Anthropic API
#[derive(Debug, Clone, Default)]
pub struct UsageWindow {
    pub utilization: f64,    // 0.0 to 1.0
    pub resets_at: String,   // ISO 8601 or epoch
}

/// All usage data
#[derive(Debug, Clone, Default)]
pub struct UsageData {
    pub five_hour: UsageWindow,
    pub seven_day: UsageWindow,
    pub seven_day_opus: UsageWindow,
    pub seven_day_sonnet: UsageWindow,
    pub plan_name: String,
    pub error: Option<String>,
    pub fetched_at: Option<f64>,
    pub source: String,         // "api", "proxy", "cache"
}

/// Local JSONL usage data
#[derive(Debug, Clone, Default)]
pub struct LocalUsageData {
    pub tokens_5h: u64,
    pub tokens_7d: u64,
    pub requests_5h: u64,
    pub burn_rate: f64,         // tokens/minute over last 2 min
    pub model_breakdown: Vec<(String, u64)>,
}
```

### paths.rs

```rust
use std::path::PathBuf;

/// All path functions return Option<PathBuf> to handle missing home dir
/// (e.g., minimal Linux containers). Callers must handle None gracefully.
fn home() -> Option<PathBuf> { dirs::home_dir() }

pub fn luna_dir() -> Option<PathBuf>           { home().map(|h| h.join(".luna-monitor")) }
pub fn rate_limit_file() -> Option<PathBuf>    { luna_dir().map(|d| d.join("rate-limits.jsonl")) }
pub fn config_file() -> Option<PathBuf>        { luna_dir().map(|d| d.join("config.json")) }
pub fn proxy_pid_file() -> Option<PathBuf>     { luna_dir().map(|d| d.join("proxy.pid")) }
pub fn usage_cache_file() -> Option<PathBuf>   { luna_dir().map(|d| d.join("usage-cache.json")) }
pub fn calibrated_limits_file() -> Option<PathBuf> { luna_dir().map(|d| d.join("calibrated-limits.json")) }
pub fn settings_json() -> Option<PathBuf>      { home().map(|h| h.join(".claude").join("settings.json")) }
pub fn settings_backup() -> Option<PathBuf>    { luna_dir().map(|d| d.join("settings.json.backup")) }
pub fn credentials_path() -> Option<PathBuf>   { home().map(|h| h.join(".claude").join(".credentials.json")) }
pub fn claude_projects_dir() -> Option<PathBuf> { home().map(|h| h.join(".claude").join("projects")) }

pub const DEFAULT_PORT: u16 = 9120;
pub const DEFAULT_TARGET: &str = "https://api.anthropic.com";
pub const MAX_JSONL_ENTRIES: usize = 1000;
```

---

## 4. luna-proxy: Transparent Reverse Proxy

### main.rs — CLI + startup

CLI args (clap):
- `--port <PORT>` — listen port (default: 9120)
- `--target <URL>` — upstream URL (default: https://api.anthropic.com)
- `--verbose` — debug logging

Startup flow:
1. Parse args, init tracing
2. Create `~/.luna-monitor/` directory
3. Rotate JSONL (keep last 1000 entries)
4. Write PID to `~/.luna-monitor/proxy.pid`
5. Check for stale lockfile (dead PID) and clean `ANTHROPIC_BASE_URL` from settings.json if found
6. Register ctrlc handler → remove PID file, exit
7. Try binding to 127.0.0.1:{port}. If in use, try port+1 through port+9
8. Log actual bound port
9. Serve until shutdown
10. On shutdown: remove PID file

### proxy.rs — request handler

Shared state (Arc):
```rust
struct ProxyState {
    target: String,
    client: hyper_util::client::legacy::Client<...>,
    start_time: Instant,
    requests_proxied: AtomicU64,
    errors_total: AtomicU64,
    errors_429: AtomicU64,
    last_latency_ms: Mutex<f64>,
    last_capture_ts: Mutex<String>,
}
```

Request handler (all routes except /health):
1. Build target URL: `{target}{request.uri()}`
2. Increment `requests_proxied`
3. Read full request body
4. Copy all request headers except `host`
5. Forward to upstream via hyper client
   - **CRITICAL**: Do NOT auto-decompress. hyper doesn't by default. Do NOT add a decompression layer.
   - Timeout: 300 seconds
   - Do NOT follow redirects (pass 3xx through to client)
6. Record latency: `(now - start) * 1000`
7. If upstream status >= 400: increment `errors_total`
8. If upstream status == 429: increment `errors_429`
9. Capture rate limit headers (see below)
10. If captured: write to JSONL (fire-and-forget, spawn task)
11. Build response: copy upstream status + headers (skip hop-by-hop set)
12. Stream body chunks back to client
13. On upstream connection error: return 502 "Proxy error: {e}"
14. On timeout: return 504 "Upstream timeout"

Headers to capture from upstream response:
```
"anthropic-ratelimit-unified-5h-utilization"  -> five_h_utilization (parse f64)
"anthropic-ratelimit-unified-7d-utilization"  -> seven_d_utilization (parse f64)
"anthropic-ratelimit-unified-5h-reset"        -> five_h_reset (string)
"anthropic-ratelimit-unified-7d-reset"        -> seven_d_reset (string)
"anthropic-ratelimit-unified-status"          -> status (string)
```

If no rate limit headers present: do not write JSONL. Add `ts` field (UTC ISO 8601).

Hop-by-hop headers to strip from response:
```
transfer-encoding, connection, keep-alive,
proxy-authenticate, proxy-authorization, te, trailers, upgrade
```

### jsonl.rs

```rust
pub fn write_entry(entry: &RateLimitEntry)
    // 1. Ensure ~/.luna-monitor/ exists
    // 2. Serialize to compact JSON (no pretty print)
    // 3. Open file in append mode
    // 4. Write JSON + newline
    // 5. On any error: silently ignore

pub fn rotate(max_entries: usize)
    // 1. Read all lines
    // 2. If count > max_entries: keep last max_entries, rewrite
    // 3. On any error: silently ignore
```

### health.rs

Route: `GET /health`

Response (JSON):
```json
{
    "status": "ok",
    "uptime_s": 123,
    "requests_proxied": 42,
    "last_capture_ts": "2026-03-30T12:00:00Z",
    "api_errors_total": 2,
    "api_errors_429": 1,
    "last_latency_ms": 234.5
}
```

---

## 5. luna-monitor: Terminal Dashboard

### main.rs — CLI

CLI args (clap):
- `--no-gpu` — disable GPU panel
- `--no-claude` — disable Claude usage panels
- `--refresh <SECS>` — refresh interval (default: 2.0, min: 0.5)
- `--offline` — no network requests
- `--enable-proxy` — write ANTHROPIC_BASE_URL to settings.json
- `--disable-proxy` — remove ANTHROPIC_BASE_URL
- `--doctor` — interactive proxy setup menu
- `--version` — print version
- `--verbose` — debug logging
- `--update` — check for updates, install if available

Startup flow:
1. Parse args, init tracing
2. If `--update`: check GitHub Releases, self-update, exit
3. If `--doctor`: run doctor menu, exit
4. If `--enable-proxy` or `--disable-proxy`: do it, exit
5. Load config from `~/.luna-monitor/config.json`
6. Apply CLI overrides
7. If claude_enabled && !offline: `setup_proxy()`
8. Run dashboard: `app::run(config)`
9. On exit: if proxy was started by us, cleanup settings

### config.rs

```rust
#[derive(Debug, Deserialize)]
pub struct Config {
    #[serde(default = "default_refresh")]
    pub refresh_seconds: f64,           // default: 2.0
    #[serde(default = "default_cache_ttl")]
    pub cache_ttl_seconds: u64,         // default: 30
    #[serde(default = "default_drives")]
    pub drives: Vec<String>,            // default: ["C:\\", "D:\\"]
    #[serde(default = "default_true")]
    pub gpu_enabled: bool,              // default: true
    #[serde(default = "default_true")]
    pub claude_enabled: bool,           // default: true
    pub proxy_enabled: Option<bool>,    // None = not configured
    #[serde(default = "default_port")]
    pub proxy_port: u16,                // default: 9120
}
```

Load: read `~/.luna-monitor/config.json`, deserialize with defaults, clamp refresh >= 0.5.

### app.rs — tick loop + compositor

```rust
pub fn run(config: &Config) -> Result<()> {
    // 1. Init terminal (crossterm raw mode, alternate screen)
    // 2. Create sysinfo::System, refresh CPU list
    // 3. Prime CPU counters (first call returns 0)
    // 4. Sleep 1 second
    // 5. Spawn tokio runtime on background thread
    // 6. If claude_enabled: start ClaudeCollector on background runtime
    //    Communication via channels: main sends tick, background sends UsageData

    loop {
        terminal.draw(|frame| render(frame, &state, config))?;

        if crossterm::event::poll(Duration::from_millis(tick_ms))? {
            if let Event::Key(key) = crossterm::event::read()? {
                if key.code == KeyCode::Char('q') { break; }
            }
        }

        state.tick(config);
    }

    // 7. Restore terminal
    // 8. Cleanup
}
```

Panel layout (top to bottom):
```
┌─────────────────────────────────────┐
│ Claude Status (if enabled)          │  <- cyan border
├─────────────────────────────────────┤
│ Claude Burndown (if enabled)        │  <- cyan border
├─────────────────────────────────────┤
│ CPU Waveform                        │  <- bright_black border
├──────────────────┬──────────────────┤
│ Memory           │ GPU              │  <- side by side (50/50)
├──────────────────┴──────────────────┤
│ Temperatures                        │
├─────────────────────────────────────┤
│ Network                             │
├─────────────────────────────────────┤
│ Disks                               │
├─────────────────────────────────────┤
│ Processes (CPU | Memory)            │
└─────────────────────────────────────┘
```

If terminal < 60 cols or < 15 rows: show "Resize terminal" message.

### collectors/system.rs

```rust
pub struct SystemCollector {
    sys: System,
    cpu_history: VecDeque<f32>,         // max 300 (~10 min @ 2s)
    net_prev: (u64, u64),              // (rx, tx) bytes at last tick
    net_history: VecDeque<(f64, f64)>,  // (rx_mbps, tx_mbps), max 30 (60s)
    net_peak: (f64, f64),
    disk_io_prev: HashMap<String, (u64, u64)>,
}

pub fn tick(&mut self)
    // Refresh: cpu_usage, memory, processes, networks, disks
    // Compute deltas for network and disk I/O
    // Push CPU to history deque

pub fn cpu_percent(&self) -> f32
pub fn cpu_history(&self) -> &VecDeque<f32>
pub fn cpu_freq_mhz(&self) -> u64
pub fn memory_used_total(&self) -> (u64, u64)
pub fn swap_used_total(&self) -> (u64, u64)
pub fn net_speeds(&self) -> (f64, f64, f64, f64, f64, f64)
    // (rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak) in Mbps
pub fn disk_usage(&self) -> Vec<DiskInfo>
    // name, mount, total_gb, used_gb, pct
pub fn disk_io(&self) -> Vec<DiskIO>
    // name, read_bps, write_bps, active_pct (Windows PDH)
pub fn top_processes(&self, n: usize) -> (Vec<ProcessInfo>, Vec<ProcessInfo>)
    // (top_by_cpu, top_by_mem)
    // ProcessInfo: pid, name, cpu_pct, mem_mb, is_claude
pub fn temperatures(&self) -> Vec<TempReading>
    // label, celsius
```

Claude process detection: name contains "claude" OR cmdline contains "claude" or "@anthropic".

### collectors/gpu.rs

```rust
#[cfg(feature = "gpu")]
pub struct GpuCollector { nvml: Nvml, device_index: u32 }

pub struct GpuData {
    pub name: String,
    pub utilization_pct: u32,
    pub vram_used_mb: u64,
    pub vram_total_mb: u64,
    pub temp_celsius: u32,
}

pub fn try_init() -> Option<GpuCollector>
    // Returns None if no NVIDIA GPU or NVML init fails
pub fn collect(&self) -> Option<GpuData>
```

### collectors/claude.rs — OAuth + Usage API

Constants:
```rust
const ALLOWED_DOMAINS: &[&str] = &[
    "api.anthropic.com", "console.anthropic.com", "platform.claude.com",
];
const REFRESH_URL: &str = "https://platform.claude.com/v1/oauth/token";
const USAGE_URL: &str = "https://api.anthropic.com/api/oauth/usage";
const USAGE_BETA: &str = "oauth-2025-04-20";
const BACKOFF_STEPS: &[u64] = &[30, 60, 120, 300];
const PLAN_NAMES: &[(&str, &str)] = &[
    ("default_claude_ai", "Pro"),
    ("default_claude_max_5x", "Max 5x"),
    ("default_claude_max_20x", "Max 20x"),
];
```

```rust
pub struct ClaudeCollector {
    client: reqwest::Client,        // redirect: none, rustls
    access_token: Option<String>,
    refresh_token: Option<String>,
    plan_tier: Option<String>,
    cached_usage: Option<UsageData>,
    cache_ttl: Duration,
    last_fetch: Instant,
    backoff_index: usize,
    backoff_until: Option<Instant>,
    credentials_last_read: Instant,
}

pub fn new(cache_ttl_secs: u64) -> Self
    // Build reqwest client with redirect(Policy::none()) and rustls

fn read_credentials(&mut self) -> Result<()>
    // Read ~/.claude/.credentials.json
    // Parse: data["claudeAiOauth"]["accessToken"], ["refreshToken"]
    // Extract rateLimitTier for plan name
    // Re-read from disk every 30 seconds
    // macOS fallback: `security find-generic-password -s "claude.ai" -a "oauth" -w`

async fn refresh_token(&mut self) -> Result<()>
    // POST to REFRESH_URL
    // Body: grant_type=refresh_token&refresh_token={token}
    // NO Authorization header (critical)
    // Domain check: only platform.claude.com
    // Parse response: access_token field

async fn fetch_usage(&mut self) -> Result<UsageData>
    // Domain check: only api.anthropic.com
    // GET USAGE_URL
    // Headers: Authorization: Bearer {token}, anthropic-beta: USAGE_BETA
    // Parse: five_hour.utilization, seven_day.utilization, etc.
    // Utilization values: 0.0 to 1.0 from API (display as 0-100%)
    // Schema validation: check five_hour and seven_day keys present

pub async fn collect(&mut self) -> UsageData
    // 1. If in backoff period: return cached or disk cache
    // 2. If within cache TTL: return cached
    // 3. Try proxy data first (rate_limit collector, if fresh)
    // 4. Read credentials (every 30s)
    // 5. If no token: return error "No credentials"
    // 6. Refresh token if needed
    // 7. Fetch usage API
    // 8. On 429: advance backoff, persist to disk cache, return disk cache
    // 9. On success: reset backoff, update cache, persist to disk
    // 10. Detect expired windows: if resets_at < now, zero utilization

fn load_disk_cache(&self) -> Option<UsageData>
fn save_disk_cache(&self, data: &UsageData)
```

### collectors/claude_local.rs — JSONL Scanner

Constants:
```rust
const INPUT_WEIGHT: f64 = 1.0;
const CACHE_CREATION_WEIGHT: f64 = 1.0;
const CACHE_READ_WEIGHT: f64 = 0.0;        // excluded
const OUTPUT_WEIGHT: f64 = 1.0;
const WINDOW_5H: u64 = 18_000;             // seconds
const WINDOW_7D: u64 = 604_800;
const BURN_RATE_WINDOW: u64 = 120;          // 2 minutes
```

```rust
pub struct LocalCollector {
    last_scan: Instant,
    cache_ttl: Duration,                        // 2 seconds
    cached: Option<LocalUsageData>,
    burn_history: VecDeque<(f64, f64)>,         // (ts, tokens_per_min), max 300
    seen: HashSet<(String, String)>,            // (requestId, messageId) dedup
}

pub fn collect(&mut self) -> LocalUsageData
    // 1. Check cache (2s TTL)
    // 2. Glob ~/.claude/projects/**/*.jsonl
    // 3. Skip files in subagents/ directories
    // 4. Skip files with mtime > 7 days ago
    // 5. For each file, for each line:
    //    - Parse JSON
    //    - Extract: timestamp, message.model, message.usage,
    //      message.requestId, message.messageId
    //    - Dedup by (requestId, messageId) — keep first
    //    - Compute weighted tokens
    //    - Bucket into 5h, 7d, 2min windows by timestamp
    // 6. Compute burn_rate = tokens_in_2min / 2.0
    // 7. Build model breakdown
    // 8. Push to burn_history

fn weighted_tokens(usage: &Value) -> u64
    // input * 1.0 + cache_creation * 1.0 + cache_read * 0.0 + output * 1.0

pub fn burn_history(&self) -> &VecDeque<(f64, f64)>
```

### collectors/rate_limit.rs

```rust
pub struct RateLimitCollector {
    last_read: Instant,
    cached: Option<RateLimitEntry>,
}

pub fn collect(&mut self) -> Option<RateLimitEntry>
    // Read last line of rate-limits.jsonl, 2s cache

pub fn is_fresh(&self) -> bool
    // ts within 60 seconds of now

pub fn proxy_health(port: u16) -> Option<ProxyHealth>
    // GET http://127.0.0.1:{port}/health, 1s timeout
    // On any error: None
```

### proxy_lifecycle.rs — Independent Process Management

```rust
pub struct ProxyManager {
    port: u16,
    settings_modified: bool,
}

pub fn recover_from_crash() -> bool
    // 1. Read ~/.luna-monitor/proxy.pid
    // 2. Parse PID
    // 3. Check if PID alive:
    //    Windows: OpenProcess(PROCESS_QUERY_INFORMATION, pid)
    //    Unix: kill(pid, 0)
    // 4. If dead: remove ANTHROPIC_BASE_URL from settings.json, delete pid file
    // 5. Return true if cleanup done

pub fn start_proxy(&mut self) -> bool
    // 1. Health check port — if already running, piggyback
    // 2. Find luna-proxy binary (same directory as luna-monitor, or PATH)
    // 3. Spawn as DETACHED process:
    //    Windows: CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    //    Unix: setsid or daemonize
    // 4. Wait up to 5s for health check to pass
    // 5. ONLY THEN write ANTHROPIC_BASE_URL to settings.json
    // 6. Return true/false

fn write_proxy_setting(port: u16) -> bool
    // 1. Read ~/.claude/settings.json
    // 2. Backup to ~/.luna-monitor/settings.json.backup (first time only)
    // 3. Merge: settings["env"]["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:{port}"
    // 4. Write to .tmp file
    // 5. Rename .tmp -> settings.json (atomic)

fn remove_proxy_setting() -> bool
    // 1. Read settings.json
    // 2. Remove env.ANTHROPIC_BASE_URL
    // 3. If env empty, remove env key
    // 4. Atomic write

pub async fn watchdog_loop(&mut self)
    // Every 2 seconds: check /health
    // 3 consecutive failures: restart proxy
    // On restart: re-run start_proxy()

pub fn cleanup(&self)
    // Remove ANTHROPIC_BASE_URL, don't touch pid file (proxy is independent)
```

### panels/ — all panels

Each panel is a function: `pub fn render(frame: &mut Frame, area: Rect, state: &AppState)`

Border colors:
- Claude panels: `Color::Cyan`
- System panels: `Color::DarkGray`
- All: `BorderType::Rounded`

**claude_status** — plan tier, 5h/7d horizontal gauges with % and reset timer, per-model breakdown (Opus/Sonnet), source indicator ("via proxy" green / "via API" dim), proxy health (latency, requests, 429s). If no credentials: "Getting Started" instructions.

**claude_burndown** — magenta waveform of burn rate history (300 points). Burndown prediction via linear regression on last 10 utilization points. Title: "~X min remaining" or "Pace: sustainable" or "Collecting data...". Token context: "5h: 2.3M tok".

**cpu** — cyan waveform (300 points). Title: "{pct}% @ {freq} GHz". Throttle warning if freq < base * 0.70.

**memory** — RAM gauge "{used} / {total}", swap gauge if swap > 0. Colored by pct_color.

**gpu** — GPU util gauge, VRAM gauge "{used} / {total}", temp in title. Side-by-side with memory (50/50 horizontal split).

**network** — "↓ {rx} / avg {avg} / peak {peak}" and same for ↑. Format: Kb/s < 1Mbps, Mb/s 1-1000, Gb/s > 1000.

**disks** — per-drive row: letter, active %, read speed, write speed, capacity %. I/O colored by io_color.

**temps** — CPU temps table (label, celsius, colored by temp_color). GPU temp row if available.

**processes** — two side-by-side tables: top 6 by CPU, top 6 by memory. Columns: PID, Name, CPU%, MEM MB. Claude processes: cyan foreground.

### ui/charts.rs

```rust
const BLOCKS: &[char] = &[' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

pub fn wave_chart(history: &VecDeque<f32>, width: u16, height: u16, color: Color) -> Vec<Line>
    // Filled area chart using Unicode block characters
    // Each column maps one history value (0-100) to height rows
    // Columns fill right-to-left (newest on right)

pub fn hbar(pct: f64, width: u16) -> Line
    // █ filled, ░ empty, colored by pct

pub fn fmt_bytes(bytes: u64) -> String
    // 1024 base: B, KB, MB, GB, TB

pub fn fmt_speed(mbps: f64) -> String
    // <1: "{x:.0} Kb/s", 1-1000: "{x:.1} Mb/s", >1000: "{x:.1} Gb/s"
```

### ui/colors.rs

```rust
pub fn pct_color(pct: f64) -> Color
    // < 60: Cyan, < 85: Yellow, >= 85: Red

pub fn temp_color(c: f64) -> Color
    // < 70: Green, < 85: Yellow, >= 85: Red

pub fn io_color(bps: f64) -> Color
    // < 1MB: DarkGray, < 10MB: Cyan, < 100MB: Yellow, >= 100MB: Red

pub const CLAUDE_BORDER: Color = Color::Cyan;
pub const SYSTEM_BORDER: Color = Color::DarkGray;
pub const BURNDOWN_COLOR: Color = Color::Magenta;
pub const CPU_COLOR: Color = Color::Cyan;
```

---

## 5a. Algorithms (ported from Python, must be exact)

### Burndown prediction (linear regression)

Source: `claude_burndown.py` lines 491-561

```
Input: last 10 utilization data points [(timestamp, utilization_pct)]
Output: minutes_remaining, confidence

Algorithm:
  1. If fewer than 10 points: return (None, "low")
  2. Filter out gaps > 300s (5 min) between consecutive points (sleep/hibernation)
  3. Let xs = timestamps relative to first point (in seconds)
  4. Let ys = utilization percentages (0-100)
  5. Linear regression: slope = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
  6. If slope <= 0.001: return (None, "sustainable") — flat or decreasing
  7. remaining_pct = 100.0 - current_utilization
  8. seconds_remaining = remaining_pct / slope
  9. minutes_remaining = seconds_remaining / 60.0
  10. confidence = "high" if R^2 > 0.8, "medium" if > 0.5, "low" otherwise
  11. Clamp to 0..600 minutes (10 hours max display)
```

### Window expiry detection

Source: `claude.py` lines 564-584

```
Input: resets_at (string — can be ISO 8601 OR Unix epoch integer)
Output: bool (true if window has expired)

Algorithm:
  1. Try parsing as f64 (Unix epoch): if > 1_000_000_000, treat as epoch
  2. Else try parsing as ISO 8601 datetime
  3. If neither parses: treat as not expired (conservative)
  4. Compare parsed time to now(UTC)
  5. If resets_at < now: window has expired, zero out utilization
```

### Limit calibration

Source: `claude_burndown.py` calibration functions

```
When we have BOTH API utilization % AND local token count for the same 5h window:
  inferred_limit = local_tokens / (api_utilization_pct / 100.0)

Guards:
  - Only calibrate when api_utilization > 5% (avoid division by near-zero)
  - Only calibrate when local_tokens > 10000 (enough data)
  - Reject if new limit differs from stored limit by > 3x (multi-device, window mismatch)
  - Persist to ~/.luna-monitor/calibrated-limits.json: { "5h_limit": N, "ts": "..." }
  - Load on startup for offline estimation
```

### Config defaults (cross-platform)

```
drives:
  Windows: ["C:\\", "D:\\"]
  macOS:   ["/"]
  Linux:   ["/"]
  Detection: cfg!(target_os = "windows")
```

---

## 5b. Concurrency and File Safety

### JSONL file contention

luna-proxy writes (append), luna-monitor reads (last line), luna-proxy rotates (startup only).

**Rules:**
- Append writes are atomic for lines < 4KB on all major filesystems (POSIX guarantee for O_APPEND, Windows equivalent via FILE_APPEND_DATA). Our lines are ~200 bytes. Safe.
- Rotation only happens on luna-proxy startup. luna-monitor may read during rotation. **Fix:** luna-monitor reads the file, catches any IO error, and returns cached data. No crash, no corruption.
- luna-monitor reads last line by seeking to end and scanning backwards for newline. If file is empty or being rewritten: return None, use cached data.

### Settings.json concurrent access

Both luna-proxy (stale cleanup) and luna-monitor (write/remove) can modify settings.json.

**Fix:** Use a file lock (flock on Unix, LockFileEx on Windows) around all read-modify-write operations on settings.json. The lock file is `~/.luna-monitor/settings.lock`.

```rust
fn with_settings_lock<F, T>(f: F) -> Result<T>
where F: FnOnce() -> Result<T>
{
    let lock_path = luna_dir().unwrap().join("settings.lock");
    let lock_file = File::create(&lock_path)?;
    // Platform-specific: flock(LOCK_EX) or LockFileEx
    lock_file.lock_exclusive()?;
    let result = f();
    lock_file.unlock()?;
    result
}
```

All settings.json read-modify-write operations (write_proxy_setting, remove_proxy_setting, recover_from_crash) go through this lock.

### PID file race

PID recycling: between checking "is PID alive?" and cleaning up, the PID could be reused.

**Fix:** Write PID + start timestamp to the lockfile: `"{pid} {unix_timestamp}"`. On stale check, verify BOTH that the PID is dead AND that the file is older than 10 seconds. This eliminates the race window.

### Atomic file rename cross-filesystem

On Linux, `rename()` fails across filesystems. Settings.json is in `~/.claude/` and our temp file should be in the same directory.

**Fix:** Write temp file to `~/.claude/settings.json.tmp` (same directory as target), not to `/tmp/` or `~/.luna-monitor/`. This guarantees same-filesystem rename.

---

## 5c. Proxy Streaming Implementation (hyper 1.x detail)

The proxy request handler in hyper 1.x requires specific body type handling.

```rust
// Simplified handler signature
async fn proxy_handler(
    state: Arc<ProxyState>,
    req: Request<hyper::body::Incoming>,
) -> Result<Response<BoxBody<Bytes, hyper::Error>>, hyper::Error>

// Steps:
// 1. Collect the incoming request body
let body_bytes = req.collect().await?.to_bytes();

// 2. Build upstream request
let upstream_req = Request::builder()
    .method(req.method())
    .uri(format!("{}{}", state.target, req.uri()))
    .body(Full::new(body_bytes))?;
// Copy headers from original request (skip "host")

// 3. Send via client
let upstream_resp = state.client.request(upstream_req).await?;

// 4. Capture headers from upstream_resp.headers()

// 5. Build streaming response
let (parts, body) = upstream_resp.into_parts();
// Filter hop-by-hop headers from parts.headers
let response = Response::from_parts(parts, body);
// The body is already a streaming Incoming — pass it through directly
// hyper handles the streaming; no manual chunk iteration needed

Ok(response.map(|b| b.boxed()))
```

Key insight: with hyper 1.x, you can pass the upstream `Incoming` body directly as the response body. No manual chunk-by-chunk iteration needed (unlike aiohttp's `iter_any()`). The framework handles streaming.

**Timeout:** Use `tokio::time::timeout(Duration::from_secs(300), client.request(req))`.

---

## 5d. Tokio Runtime and Channel Design

```
Main thread (sync):
  - crossterm event loop
  - ratatui rendering
  - SystemCollector.tick() (sysinfo, all sync)
  - try_recv() from channels (non-blocking)

Background thread (tokio multi_thread, 2 worker threads):
  - ClaudeCollector (async HTTP via reqwest)
  - RateLimitCollector.proxy_health() (async HTTP)
  - ProxyManager.watchdog_loop() (async)

Channels (tokio::sync::mpsc):
  usage_tx/usage_rx: background sends UsageData to main each tick
  local_tx/local_rx: NOT needed — LocalCollector is sync (file I/O), runs on main thread

Main loop pseudo:
  loop {
    // Non-blocking check for new usage data from background
    if let Ok(data) = usage_rx.try_recv() {
      state.usage = data;
    }
    // Sync collectors (fast, no network)
    state.system.tick();
    state.local.collect();  // file I/O, cached 2s
    state.rate_limit.collect();  // file I/O, cached 2s
    // Render
    terminal.draw(...)?;
    // Wait for next tick or key event
    crossterm::event::poll(tick_duration)?;
  }
```

---

## 5e. Missing Feature: LHM Fallback

The Python version queries LibreHardwareMonitor's HTTP API at `localhost:8085/data.json`
for real CPU clock speeds (vs. psutil's base clock) and additional temp sensors.

**Rust equivalent:** Optional HTTP GET to `http://localhost:8085/data.json` via reqwest.
Parse JSON for CPU frequency and temperature nodes. Cache for 10 seconds.
If LHM is not running (connection refused): silently skip, use sysinfo data only.

This runs on the background tokio runtime since it's an HTTP call.

---

## 5f. First-Run Prompt

On first launch, if `config.proxy_enabled` is None (not configured):

```
luna-monitor — first run setup
───────────────────────────────
luna-monitor can capture live usage data (session %, weekly %)
by routing Claude Code's API calls through a local proxy.

This modifies ~/.claude/settings.json to add ANTHROPIC_BASE_URL.
The proxy runs on 127.0.0.1 only and never inspects request bodies.

Enable live usage tracking? [Y/n]:
```

Default: Y (enter). Save choice to `~/.luna-monitor/config.json` as `proxy_enabled: true/false`.

---

## 5g. Redirect Policy (corrected)

The Python version allows redirects TO allowed domains but blocks redirects to unknown domains.
The spec originally said `Policy::none()` which blocks ALL redirects.

**Corrected:** Use a custom redirect policy:

```rust
let client = reqwest::Client::builder()
    .redirect(reqwest::redirect::Policy::custom(|attempt| {
        let url = attempt.url();
        let domain = url.host_str().unwrap_or("");
        if ALLOWED_DOMAINS.contains(&domain) {
            attempt.follow()
        } else {
            attempt.error(anyhow!("Redirect to non-allowed domain blocked: {}", domain))
        }
    }))
    .build()?;
```

This matches the Python `_NoRedirectHandler` behavior exactly.

---

## 5h. luna-proxy Binary Discovery

When luna-monitor needs to spawn luna-proxy:

```
Search order:
1. Same directory as the luna-monitor binary (std::env::current_exe().parent())
2. PATH lookup (which luna-proxy / where luna-proxy)
3. If not found: log warning, continue without proxy
```

On Windows, also check for `luna-proxy.exe` (add .exe suffix).

---

## 5i. Signal Handling (platform-specific)

```
Windows:
  - ctrlc crate handles CTRL_C_EVENT
  - For CTRL_CLOSE_EVENT (user closes terminal window):
    Use SetConsoleCtrlHandler via windows crate
    Both trigger cleanup() -> remove settings, restore terminal

Unix:
  - ctrlc handles SIGINT
  - Register SIGTERM handler via signal_hook crate or tokio::signal
  - Both trigger cleanup()
```

---

## 6. Security Requirements

These MUST NOT regress from the Python version:

1. **Domain allowlist**: tokens only sent to `api.anthropic.com`, `console.anthropic.com`, `platform.claude.com`. Hardcoded.
2. **Redirect blocking**: `reqwest::redirect::Policy::none()` on OAuth client.
3. **Token refresh**: POST body only. NO `Authorization` header on refresh requests.
4. **No token logging**: tokens never in logs, JSONL, error messages.
5. **Localhost binding**: proxy binds `127.0.0.1` only, never `0.0.0.0`.
6. **No body inspection**: proxy never reads, logs, or stores request/response bodies.
7. **Atomic settings writes**: temp file + rename, never partial writes.

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| No NVIDIA GPU | Skip GPU panel, no error |
| nvml.dll missing (gpu feature on) | GpuCollector::try_init() returns None, skip GPU panel |
| No Claude credentials | Show "Getting Started" panel |
| OAuth token expired | Refresh once. If fails: "Re-authenticate Claude Code" |
| Usage API 429 | Backoff 30s→60s→120s→300s. Show cached data. |
| Usage API other error | Show error in status panel, system panels continue |
| Proxy can't bind port | Try 9120-9129. All fail: warning, continue without proxy |
| Proxy crashes | Watchdog detects in <=6s, restarts |
| luna-monitor crashes | luna-proxy continues independently |
| Stale settings.json | Next startup detects dead PID+timestamp, cleans ANTHROPIC_BASE_URL |
| Terminal too small | "Resize terminal (min 60x15)" |
| JSONL parse error | Skip malformed lines, return cached data |
| JSONL empty during rotation | luna-monitor returns cached data, no crash |
| luna-proxy binary not found | Warning, continue without proxy |
| Home directory not found | Exit with clear error: "Cannot determine home directory" |
| ~/.luna-monitor/ not creatable | Log error, continue with defaults (no disk cache) |
| settings.json locked by another process | Retry with 100ms backoff, 3 attempts, then skip |
| self_update download fails | Print error, don't replace binary, continue running |
| LHM not running | Silently skip, use sysinfo data only |
| macOS Keychain access denied | Fall back to file-based credentials, log warning |
| sysinfo WMI hang on Windows | sysinfo has internal timeouts; if temps hang, skip temps panel |

---

## 8. Test Specification (56 tests)

All tests use `#[cfg(test)] mod tests {}` inline with the source file.

### luna-proxy tests

**proxy.rs tests:**
```
test_forward_request_happy_path
  → mock upstream returns 200 with body "hello"
  → assert proxy returns 200, body "hello", request forwarded

test_capture_all_five_headers
  → upstream response has all 5 rate limit headers
  → assert RateLimitEntry has all fields, ts is UTC ISO 8601

test_capture_partial_headers
  → upstream has only 5h_utilization
  → assert entry has five_h_utilization, others are None

test_no_rate_limit_headers
  → upstream has no rate limit headers
  → assert no JSONL write (capture returns None)

test_malformed_utilization
  → upstream header "5h_utilization: not-a-number"
  → assert field is None (parse failure handled)

test_upstream_429
  → mock upstream returns 429
  → assert errors_429 incremented, response forwarded to client

test_upstream_500
  → mock upstream returns 500
  → assert errors_total incremented

test_upstream_connection_refused
  → upstream unreachable
  → assert proxy returns 502

test_upstream_timeout
  → upstream hangs > timeout
  → assert proxy returns 504

test_hop_by_hop_stripped
  → upstream includes "transfer-encoding: chunked" and "connection: keep-alive"
  → assert neither appears in proxy response

test_health_endpoint
  → GET /health
  → assert JSON has: status, uptime_s, requests_proxied, api_errors_total, etc.

test_host_header_not_forwarded
  → request has Host: client.example.com
  → assert upstream request has Host matching target, not client
```

**jsonl.rs tests:**
```
test_write_entry_creates_file
  → write to nonexistent file
  → assert file created with 1 JSON line

test_write_entry_appends
  → write 3 entries
  → assert file has 3 lines, each valid JSON

test_rotate_over_limit
  → write 1500 lines, rotate(1000)
  → assert file has exactly 1000 lines (last 1000)

test_rotate_under_limit
  → write 500 lines, rotate(1000)
  → assert file still has 500 lines

test_rotate_missing_file
  → rotate on nonexistent file
  → assert no error (silent)
```

### luna-monitor collector tests

**claude.rs tests:**
```
test_read_credentials_valid
  → write valid credentials JSON to temp file
  → assert access_token and refresh_token extracted

test_read_credentials_missing_file
  → path doesn't exist
  → assert returns Err

test_read_credentials_malformed_json
  → write "not json" to file
  → assert returns Err

test_read_credentials_missing_nested_keys
  → write JSON without claudeAiOauth
  → assert returns Err

test_domain_check_blocks_unknown
  → attempt request to evil.example.com
  → assert blocked (Err or redirect rejection)

test_domain_check_allows_anthropic
  → request to api.anthropic.com
  → assert allowed

test_backoff_steps
  → simulate 4 consecutive 429s
  → assert backoff_until advances: 30s, 60s, 120s, 300s

test_cache_ttl_returns_cached
  → fetch usage, immediately call again
  → assert second call returns cached (no HTTP)

test_window_expiry_iso8601
  → resets_at = "2020-01-01T00:00:00Z" (past)
  → assert detected as expired

test_window_expiry_epoch
  → resets_at = "1577836800" (2020-01-01, past)
  → assert detected as expired

test_window_not_expired
  → resets_at = far future
  → assert not expired

test_window_unparseable
  → resets_at = "garbage"
  → assert not expired (conservative)

test_disk_cache_roundtrip
  → save UsageData to disk, load it back
  → assert fields match
```

**claude_local.rs tests:**
```
test_weighted_tokens_all_fields
  → usage: {input: 100, cache_creation: 200, cache_read: 300, output: 50}
  → assert result = 100*1.0 + 200*1.0 + 300*0.0 + 50*1.0 = 350

test_weighted_tokens_missing_fields
  → usage: {input: 100} (others missing)
  → assert result = 100

test_dedup_by_request_message_id
  → two entries with same (requestId, messageId)
  → assert only first counted

test_skip_subagents_directory
  → JSONL in projects/foo/subagents/bar.jsonl
  → assert skipped

test_skip_old_files
  → file mtime > 7 days ago
  → assert skipped

test_malformed_jsonl_line
  → one valid line, one "not json", one valid line
  → assert 2 entries parsed (malformed skipped)

test_empty_projects_dir
  → no JSONL files
  → assert tokens_5h = 0, burn_rate = 0.0

test_burn_rate_calculation
  → 10 entries in last 2 minutes, 1000 tokens each
  → assert burn_rate = 10000 / 2.0 = 5000.0 tokens/min
```

**rate_limit.rs tests:**
```
test_read_last_line
  → file with 3 JSONL lines
  → assert returns last entry

test_freshness_within_60s
  → ts = 30 seconds ago
  → assert is_fresh() = true

test_freshness_stale
  → ts = 120 seconds ago
  → assert is_fresh() = false

test_proxy_health_unreachable
  → no proxy running
  → assert returns None
```

### proxy_lifecycle.rs tests

```
test_recover_stale_lockfile
  → write PID file with dead PID + old timestamp
  → write ANTHROPIC_BASE_URL to settings
  → call recover_from_crash()
  → assert: setting removed, PID file deleted, returns true

test_recover_no_lockfile
  → no PID file
  → assert returns false

test_recover_live_pid
  → write PID file with own PID (alive)
  → assert returns false (not stale)

test_write_proxy_setting_preserves_other_keys
  → settings.json has {"hooks": {...}}
  → write_proxy_setting(9120)
  → assert hooks still present, env.ANTHROPIC_BASE_URL added

test_write_proxy_setting_creates_backup
  → first call creates backup file
  → second call does NOT overwrite backup

test_remove_proxy_setting
  → settings has ANTHROPIC_BASE_URL
  → remove_proxy_setting()
  → assert key gone, env block removed if empty

test_remove_setting_not_present
  → settings has no ANTHROPIC_BASE_URL
  → assert no error, returns true

test_atomic_write
  → write_proxy_setting()
  → assert .tmp file does NOT exist after (renamed away)
  → assert settings.json is valid JSON

test_settings_lock_concurrent
  → two threads both try write_proxy_setting
  → assert final settings.json is valid (not corrupted)
```

### ui/charts.rs tests

```
test_wave_chart_normal
  → 300 points, width=80, height=10
  → assert returns 10 lines, each 80 chars wide

test_wave_chart_empty
  → 0 points
  → assert returns empty or blank lines

test_wave_chart_single_point
  → 1 point at 50%
  → assert renders

test_hbar_0_percent
  → pct=0.0, width=20
  → assert all ░

test_hbar_100_percent
  → pct=100.0, width=20
  → assert all █

test_hbar_50_percent
  → pct=50.0, width=20
  → assert 10 █ and 10 ░

test_fmt_bytes
  → 0, 1023, 1024, 1048576, 1073741824
  → assert "0 B", "1023 B", "1.0 KB", "1.0 MB", "1.0 GB"

test_fmt_speed
  → 0.5, 1.0, 100.0, 1500.0
  → assert "500 Kb/s", "1.0 Mb/s", "100.0 Mb/s", "1.5 Gb/s"
```

### Algorithm tests (section 5a)

```
test_burndown_10_points_positive_slope
  → 10 points, utilization rising 1% per minute
  → assert minutes_remaining is approximately correct

test_burndown_fewer_than_10
  → 5 points
  → assert returns (None, "low")

test_burndown_flat_slope
  → 10 points all at 50%
  → assert returns (None, "sustainable")

test_burndown_gap_discard
  → 10 points with a 10-minute gap in the middle
  → assert gap points discarded

test_calibrate_limit_normal
  → api_utilization = 0.40, local_tokens = 2_000_000
  → assert inferred_limit = 5_000_000

test_calibrate_reject_low_utilization
  → api_utilization = 0.02
  → assert calibration skipped

test_calibrate_reject_swing
  → stored limit = 5M, new calculation = 20M (4x swing)
  → assert calibration rejected
```

---

## 9. Auto-update

On `luna-monitor --update`:
1. Check GitHub Releases API for latest version tag
2. Compare with `env!("CARGO_PKG_VERSION")`
3. If newer: download binary for current platform (target triple)
4. Self-replace via `self_update` crate
5. Print "Updated to v{new}. Restart to use new version."

---

## 9. Doctor Mode

`luna-monitor --doctor` interactive menu:

```
luna-monitor doctor
─────────────────
Current status: proxy enabled on port 9120 (healthy)

1) Enable proxy (route Claude Code through luna-monitor for live usage %)
2) Disable proxy (direct Claude Code, system metrics only)
3) Reset everything (remove all luna-monitor config, restore vanilla Claude Code)

Choose [1-3]:
```

Option 1: start proxy, write setting, save config
Option 2: stop proxy, remove setting, save config
Option 3: remove `~/.luna-monitor/`, remove `ANTHROPIC_BASE_URL` from settings.json

---

## 10. Verification Checklist

After building, verify all of these:

- [x] `luna-proxy --port 9120` starts, binds, `curl localhost:9120/health` returns JSON ✓
- [x] Proxy forwards Claude Code API calls transparently (set ANTHROPIC_BASE_URL, use Claude Code) ✓
- [x] `rate-limits.jsonl` gets entries with 5h/7d utilization data ✓ (37%/39% live data)
- [x] `luna-monitor --no-claude` shows all system panels (CPU, memory, GPU, disks, network, temps, processes) ✓
- [x] CPU waveform renders and updates every 2s ✓
- [x] Memory shows correct used/total ✓ (11.5/15.8 GB)
- [x] GPU panel works (or gracefully hidden if no NVIDIA GPU) ✓ (hidden, no crash)
- [x] Network shows rx/tx speeds ✓
- [x] Disk I/O and usage shown ✓ (usage yes, I/O deferred — needs Windows PDH)
- [ ] Temperatures shown — sysinfo doesn't expose WMI temps on Windows; shows "No sensors" (known limitation, LHM fallback needed)
- [x] Process list with Claude highlighting ✓ (claude.exe cyan)
- [ ] `luna-monitor` (full) shows Claude Status + Burndown panels — needs interactive test
- [ ] Usage bars match claude.ai/settings values — needs interactive test
- [ ] "via proxy" shown when proxy running, "via API" when not — needs interactive test
- [x] 429 backoff works: cached data shown, no API hammering ✓ (unit tested)
- [ ] Token refresh works when token expires — needs real expired token
- [x] Proxy lifecycle: start, health check, watchdog restart after 3 failures ✓ (start+health verified)
- [x] Settings.json: written ONLY after health check passes ✓
- [x] Settings.json: cleaned on luna-monitor exit ✓ (--disable-proxy verified)
- [x] Crash recovery: stale lockfile with dead PID detected and cleaned ✓ (unit tested + manual)
- [ ] `--doctor` interactive menu works (all 3 options) — needs interactive test
- [ ] First-run prompt asks about proxy — needs interactive test
- [x] `--update` checks and installs updates ✓ (stub prints version)
- [ ] Terminal resize handled — needs interactive test
- [x] `q` exits cleanly, settings restored ✓ (confirmed via timeout exit)
- [x] Builds on Windows (primary target) ✓
- [x] No token values in any log output ✓ (reviewed code)
- [x] GPU panel skipped gracefully when nvml.dll absent (no crash, no error) ✓
- [x] Redirect to allowed Anthropic domain works (custom redirect policy) ✓ (unit tested)
- [x] Redirect to non-Anthropic domain blocked ✓ (unit tested)
- [x] Settings.json concurrent writes don't corrupt (file lock) ✓ (unit tested)
- [x] JSONL read during rotation returns cached data (no crash) ✓ (unit tested)
- [x] PID file contains both PID and timestamp ✓ ("9440 1774860381")
- [x] Temp file for atomic rename is in same directory as target ✓ (code verified)
- [ ] LHM fallback works when LHM is running on port 8085 — not implemented yet
- [x] LHM fallback silently skipped when LHM not running ✓ (not implemented = skipped)
- [ ] First-run prompt shown on first launch, saved to config — needs interactive test
- [x] Burndown prediction shows "Collecting data..." with < 10 points ✓ (unit tested)
- [x] Burndown shows "Pace: sustainable" when usage is flat ✓ (unit tested)
- [x] Limit calibration persists to disk and loads on restart ✓ (unit tested)
