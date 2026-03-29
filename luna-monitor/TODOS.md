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
1. Decide: keep Claude Status panel (shows stale/empty data) or hide it until API works?
2. Redesign Activity panel around JSONL-only data (waveform is the real value)
3. Monitor Anthropic's statusLine JSON feature request — when they ship it, we get free utilization %
4. Consider: should luna-monitor BE a statusLine command instead of a separate tool?

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
