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

### Phase 1: Proxy Gateway Experiment (NEXT SESSION)

The core problem: we need the **denominator** (utilization %) to make the dashboard meaningful. Counting tokens without knowing the limit is just a number with no context. The only real-time source of utilization % is the rate limit headers on every API response — but Claude Code doesn't expose them.

**Experiment: API proxy that intercepts rate limit headers**

Inspired by ccNexus (810 stars, active). Sit a local proxy between Claude Code and `api.anthropic.com`. Capture these headers from every completion response:
- `anthropic-ratelimit-unified-5h-utilization` → session %
- `anthropic-ratelimit-unified-7d-utilization` → weekly %
- `anthropic-ratelimit-unified-*-resets-at` → reset timestamps

**Experiment steps:**
1. Build minimal transparent HTTPS proxy (mitmproxy or custom)
2. Configure Claude Code to route through it (`ANTHROPIC_BASE_URL` or system proxy)
3. Verify headers are present and parseable on real responses
4. Feed captured data to luna-monitor via shared file or socket
5. Measure: does it add latency? Does Claude Code work normally through it?

**Key question:** Can Claude Code be configured to use a custom base URL or proxy? Check `ANTHROPIC_BASE_URL`, `HTTP_PROXY`, `HTTPS_PROXY` env vars, or Claude Code settings.

**Reference implementations:**
- `lich0821/ccNexus` (810★, active) — full proxy with credential rotation, token pool, multi-format support
- `steipete/CodexBar` (9.5K★, active) — multi-method fallback: OAuth → browser cookies → CLI PTY

### Phase 2: Alternatives (if proxy doesn't work)

**2a. Web cookie endpoint** — `claude.ai/api/organizations/{orgId}/usage` via browser cookies. Separate rate limit bucket from OAuth, no 429s. Fragile (cookies expire) but proven by CodexBar.

**2b. Statusline JSON** — Monitor Anthropic feature requests:
- [Issue #27915](https://github.com/anthropics/claude-code/issues/27915) — Expose rate-limit data in statusLine JSON (30+ upvotes)
- [Issue #34074](https://github.com/anthropics/claude-code/issues/34074) — Add rate limit utilization to status line JSON
- [Issue #38380](https://github.com/anthropics/claude-code/issues/38380) — Expose usage/rate limit data via CLI flag or hook event

**2c. OTel telemetry** — `CLAUDE_CODE_ENABLE_TELEMETRY=1` pipes data to OpenTelemetry collector. `claude-code-otel` (322★) did this but is stale (last push Jun 2025). Heavy but enterprise-grade.

### Phase 3: Full Sprint (once data source is proven)

Once we know which method reliably delivers utilization %, run a full `/autoplan` sprint to:
1. Incorporate mature JSONL parsing from ccusage (dedup, weighting, window alignment)
2. Wire proven utilization source into Claude Status panel
3. Build real burndown: tokens spent + limit + burn rate → "~Xh remaining"
4. Consider: should luna-monitor BE a statusLine command?

### Old questions (still open)
1. Decide: keep Claude Status panel (shows stale/empty data) or hide it until data source works?
2. Redesign Activity panel around JSONL-only data (waveform is the real value)

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

## DONE (this session — session 2)

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
