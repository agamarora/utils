# luna-monitor — Outstanding TODOs

Last updated: 2026-03-29

---

## BLOCKER: Usage API rate limit (429) — ROOT CAUSE FOUND

**Status:** Root cause confirmed. Anthropic's `/api/oauth/usage` endpoint is broken for everyone. Not a luna-monitor bug.

**Root cause:** Anthropic's usage endpoint has aggressive rate limiting that makes it unusable for monitoring. This is a known issue with 7+ open GitHub issues since March 2-3, 2026. `Retry-After: 0` but 429 persists indefinitely.

**Evidence:**
- [Issue #31021](https://github.com/anthropics/claude-code/issues/31021) — OAuth usage API returns persistent 429
- [Issue #30930](https://github.com/anthropics/claude-code/issues/30930) — persistent 429 for Max users
- [Issue #31637](https://github.com/anthropics/claude-code/issues/31637) — endpoint aggressively rate limits
- Disabling Pulse (statusLine) does NOT fix it — rate limit is per-account
- Raw API call with clean User-Agent still returns 429

**Key discovery:** Claude Code already parses rate limit headers from EVERY completion API response:
- `anthropic-ratelimit-unified-5h-utilization` (session %)
- `anthropic-ratelimit-unified-7d-utilization` (weekly %)

These headers give exact utilization % without the usage endpoint. But Claude Code does NOT expose them to external tools or in JSONL files.

**Feature requests to watch:**
- [Issue #27915](https://github.com/anthropics/claude-code/issues/27915) — Expose rate-limit data in statusLine JSON (30+ upvotes, most duplicated request)
- [Issue #34074](https://github.com/anthropics/claude-code/issues/34074) — Add rate limit utilization to status line JSON

**What this means for luna-monitor:**
- The Claude Status panel (utilization bars) is unreliable until Anthropic fixes the endpoint or exposes rate limit data in statusLine JSON
- The Activity panel should rely on JSONL data only (activity waveform, token counts)
- System monitoring panels (CPU, GPU, memory, disks, etc.) work perfectly and are the real value today

**Current mitigations in place:**
- Window expiry detection: if `resets_at` is in the past, stale data is zeroed out
- Exponential backoff: 30s → 60s → 120s → 300s to avoid hammering the endpoint
- Disk cache: survives restarts, used during 429 (but correctly detects expired windows)
- Pulse disabled as statusLine (was competing for same endpoint)

**Next steps when resuming:**

### Phase 1: Proxy Gateway Experiment — DONE (session 3)

**Result: SUCCESS.** Built aiohttp reverse proxy. Captured live headers from real Claude Code traffic:
- `5h_utilization: 0.38-0.40` (session 38-40%)
- `7d_utilization: 0.23-0.24` (weekly 23-24%)
- `5h_reset: 1774796400` (epoch, not ISO — handled)
- `status: "allowed"`

**Key findings:**
- `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` env block routes Claude Code through local proxy. Confirmed working.
- Must set `auto_decompress=False` in aiohttp ClientSession to avoid ZlibError (double decompression).
- Reset timestamps come as Unix epoch, not ISO 8601. `_parse_reset_ts()` handles both.
- Anthropic SDK retries on ECONNREFUSED: 2 retries, 500ms + 1s backoff, 1.5s total window. Verified from actual SDK source (`@anthropic-ai/sdk core.js`).
- Claude Code without proxy running: fails with "Execution error" after retries (~2-3s hang).

### Phase 2: luna-monitor v2 — Unified Bulletproof Dashboard (NEXT SESSION)

**Goal:** Single `pip install luna-monitor && luna-monitor` experience. No separate proxy. No manual settings.json editing. No LHM dependency.

**Plan file:** `~/.claude/plans/shimmying-napping-stardust.md` (reviewed via /autoplan, approved)

**5 Safety Layers for the embedded proxy:**
1. **Watchdog thread** — restarts proxy within 500ms (inside SDK retry window)
2. **atexit + signal cleanup** — removes ANTHROPIC_BASE_URL on clean shutdown
3. **Crash recovery on startup** — detects stale config from prior crash via PID lockfile
4. **SDK retry tolerance** — 1.5s window covers proxy restart (verified from SDK source)
5. **Manual escape hatch** — `luna-monitor --disable-proxy` removes config instantly

**What to build (10 files, ~400 new lines):**
1. `proxy/lifecycle.py` (new) — start/stop proxy thread, settings.json management, lockfile
2. `proxy/watchdog.py` (new) — health monitor, auto-restart, failure counter
3. `proxy/server.py` (modify) — add `run_in_thread()` for embedded mode
4. `__main__.py` (modify) — add --enable-proxy/--disable-proxy, lifecycle hooks
5. `config.py` (modify) — add proxy_enabled, proxy_port settings
6. `app.py` (modify) — wire proxy start/stop into main loop
7. `panels/claude_status.py` (modify) — proxy status indicators
8. `collectors/platform_win.py` (modify) — replace LHM with WMI for temps
9. `pyproject.toml` (modify) — add wmi dependency
10. 16 new tests covering all safety layers

**settings.json management rules:**
- Always read-parse-merge, never overwrite
- Atomic write (temp file + rename)
- Backup original on first modification
- Only touch `env.ANTHROPIC_BASE_URL`, nothing else

**First-run UX:**
```
luna-monitor can show live Claude Code usage (session %, weekly %, time remaining)
by routing API calls through a local proxy. Enable? [Y/n]
```

**Reference implementations:**
- `lich0821/ccNexus` (810★) — full Go proxy, confirms ANTHROPIC_BASE_URL pattern
- `steipete/CodexBar` (9.5K★) — multi-method fallback approach

### Ecosystem context (researched 2026-03-29)

| Tool | Stars | Method | Status |
|---|---|---|---|
| ccusage | 12,076 | JSONL parsing | Active (today) |
| claude-hud | 14,822 | Claude Code plugin | Active (yesterday) |
| CodexBar | 9,528 | Multi-method (OAuth → cookies → CLI) | Active (today) |
| CCometixLine | 2,419 | Rust statusline + JSONL | Active (2 weeks ago) |
| tokscale | 1,399 | JSONL across 15+ tools | Active (4 days ago) |
| ccNexus | 810 | API proxy/gateway | Active (last week) |
| claude-code-otel | 322 | OpenTelemetry | Stale (Jun 2025) |

---

## HIGH: Replace LHM with pure Python

**What:** LibreHardwareMonitor requires downloading a separate exe, running it as admin, and enabling its web server. Users without it get no temperature or real clock speed data.

**Goal:** Ship a simpler base tier with only pip dependencies.

**Options to investigate:**
- `wmi` Python package — queries WMI for CPU temps and speeds without LHM
- `pythonnet` + direct hardware access
- `psutil.cpu_freq()` already gives current/min/max freq (not per-core temps though)
- Accept no temps in base tier, keep LHM as optional enhancement

**Decision:** Ship without LHM in base. Temps are bonus, not core value. The core value is Claude usage + CPU/memory/disk/network — all of which work with psutil alone.

---

## MEDIUM: Token counting accuracy

**What we fixed this session:**
- Streaming deduplication: Claude Code logs same API call multiple times with growing output_tokens. Deduped by (requestId, messageId). Matches ccusage behavior.
- cache_read weight: changed from 0.1x to 0.0x. Cache reads are re-reads of existing context (106M raw in a 5h session), not real work. Excluding them gives 1.5M instead of 12M — a number that makes sense for a Max 5x plan.

**Remaining questions:**
- Should we keep first occurrence (like ccusage) or last occurrence (which has final output_tokens)?
- Keeping first systematically undercounts output tokens, but output is <5% of total, so impact is small
- The calibration logic (infer limit from API % + local tokens) has a time window mismatch: API's 5h window is fixed, our JSONL window is rolling. Could align using `resets_at`.

---

## LOW: Test coverage for calibration logic

The calibration code in `claude_burndown.py` has 0 tests:
- `_calibrate_limit()` — threshold, ratio guard, disk persistence
- `_estimate_utilization()` — limit lookup, clamping
- `_load_limit_from_disk()` / `_save_limit_to_disk()` — file I/O
- Window expiry detection in `claude.py` — `_window_expired()`, `_reset_expired_usage()`

Currently 253 tests passing across all modules.

---

## DONE (session 3 — proxy experiment)

- [x] Built aiohttp reverse proxy (`proxy/server.py`, 215 lines)
- [x] CLI entry point (`proxy/cli.py`, `luna-proxy` command)
- [x] Rate limit collector (`collectors/rate_limit.py`, reads proxy JSONL)
- [x] Wired proxy data into `claude.py:_try_proxy_data()` — bypasses broken usage API
- [x] "via proxy" / "via API" indicator in Status panel
- [x] Fixed ZlibError: `auto_decompress=False` in aiohttp ClientSession
- [x] Fixed epoch timestamps: `_parse_reset_ts()` handles both epoch and ISO
- [x] Health endpoint (`GET /health`) for watchdog monitoring
- [x] JSONL rotation (keep last 1000 entries on startup)
- [x] Atomic JSONL write via `os.O_APPEND`
- [x] Verified headers present on real Claude Code traffic (5h: 40%, 7d: 24%)
- [x] Verified SDK retry behavior from source (2 retries, 1.5s window)
- [x] 285 tests passing (31 new: 18 proxy + 14 rate_limit)

## DONE (session 2)

- [x] Streaming deduplication: (requestId, messageId) dedup matches ccusage
- [x] cache_read weight 0.1x → 0.0x (tokens now reflect real work: 1.5M not 12M)
- [x] Added `requests_5h` to LocalUsageData
- [x] Removed model breakdown from Activity panel (clutter)
- [x] Wired burndown prediction into Activity panel
- [x] Calibration: infer 5h limit from API % + local tokens, persist to disk
- [x] Ratio guard: reject calibrations that swing >3x (multi-device, window mismatch)
- [x] Window expiry detection: zero out stale utilization when `resets_at` is past
- [x] NaN/Inf guard on `_parse_window` (corrupted disk cache)
- [x] Fixed stale docstring (cache_read 0.1x → 0.0x)
- [x] Investigated 429 root cause: Anthropic endpoint broken (7+ GitHub issues)
- [x] Disabled Pulse statusLine (was competing for same broken endpoint)
- [x] 253 tests passing

## DONE (session 1)

- [x] Built full luna-monitor package from scratch (modular: collectors/, panels/, ui/)
- [x] Claude OAuth credential reading (nested path `claudeAiOauth.accessToken`)
- [x] Usage API call with correct headers (`anthropic-beta: oauth-2025-04-20`)
- [x] Disk cache (`~/.luna-monitor/usage-cache.json`) — survives restarts and 429s
- [x] Utilization scale fixed: 0-100 not 0-1
- [x] Exponential backoff on 429: 30s → 60s → 120s → 300s
- [x] Burndown prediction: linear regression with reset detection
- [x] 190 tests passing
- [x] Pushed to `origin/dev/buddy`
