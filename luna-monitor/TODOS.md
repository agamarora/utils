# luna-monitor — Outstanding TODOs

Last updated: 2026-03-29

---

## BLOCKER: Usage API rate limit (429)

**Status:** Under investigation. Both luna-monitor and Claude Pulse are stuck showing 59% (stale) while the actual Claude.ai dashboard shows 72%.

**What we know:**
- The Anthropic usage endpoint (`api.anthropic.com/api/oauth/usage`) returns `HTTP 429` with `Retry-After: 0`
- Both luna-monitor and Pulse are getting 429 — this is NOT luna-monitor-specific
- The token is valid (same token, same headers as Pulse)
- Sending a raw request with `User-Agent: test/1.0` also gets 429
- The rate limit may be per-account, per-IP, or per-minute at the Anthropic side
- `Retry-After: 0` is misleading — it does not immediately clear

**Root cause hypotheses (to investigate next session):**
1. **Shared per-token rate limit**: Running Pulse AND luna-monitor both hitting the same endpoint with the same token counts double against a per-minute quota
2. **Per-minute cap on the undocumented endpoint**: May have a very low quota (e.g., 2-5 req/min) that aggressive polling exceeds
3. **Token needs refresh**: The cached token may be valid for auth but the usage API requires a fresher token
4. **IP-rate-limit**: Anthropic may rate-limit by source IP, not just by token

**Next investigation steps:**
- Stop Pulse completely, wait 5 minutes, then test luna-monitor alone
- Check if token refresh triggers a new access token that succeeds on the usage endpoint
- Try a manual `curl` with the token after both tools are stopped
- Check `~/.claude/projects/*/sessions/*.jsonl` as an alternative local data source (no API needed)
- Consider exponential backoff: current retry is flat, not backoff

**Workaround in place:**
- Disk cache at `~/.luna-monitor/usage-cache.json` — seeded from Pulse cache
- Shows last known values with reset timers counting down correctly
- System panels continue working normally

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

**Implementation:**
- Remove LHM from README "Optional" section or demote it further
- Make `collect_temps_lhm()` a no-op when LHM is not running (already implemented)
- Replace real clock speed fallback — use `psutil.cpu_freq().current` when LHM not available
- Consider `wmi` as optional tier 2 (same pattern as pynvml)

---

## MEDIUM: Two-tier install

**Base tier** (currently implemented):
- `psutil` — CPU, memory, network, disk, processes
- `rich` — terminal UI
- No admin, no downloads, no extras

**Enhanced tier** (optional):
- `pynvml` — NVIDIA GPU stats
- `wmi` — CPU temps without LHM (Windows only)

**Implementation:**
- `pyproject.toml` optional extras: `pip install luna-monitor[gpu]`, `pip install luna-monitor[temps]`
- README updated to show both tiers clearly

---

## LOW: Usage burndown panel blocked by 429

The burndown chart needs 2+ fresh data points added to `_usage_history`. Since every API call returns 429, no new points are added and it shows "Waiting for usage data...".

Once the 429 blocker is resolved, the burndown will start populating automatically.

---

## LOW: Test coverage

Currently 190 tests. A few gaps:
- `config.py` edge cases: drives list validation, invalid JSON
- `app.py` compositor integration test
- `platform_win.py` PDH initialization (requires mocks)

---

## DONE (this session)

- [x] Built full luna-monitor package from scratch (modular: collectors/, panels/, ui/)
- [x] Claude OAuth credential reading (nested path `claudeAiOauth.accessToken`)
- [x] Usage API call with correct headers (`anthropic-beta: oauth-2025-04-20`)
- [x] Disk cache (`~/.luna-monitor/usage-cache.json`) — survives restarts and 429s
- [x] Utilization scale fixed: 0-100 not 0-1
- [x] Weekly timer: shows days+hours (e.g., "4d 20h") not hours
- [x] Transient errors ("Rate limited", "cached data") hidden from UI
- [x] Burndown prediction: linear regression with reset detection
- [x] CPU throttle detection: uses `psutil.cpu_freq().max` not hardcoded 2500MHz
- [x] Credential file cache: 30s TTL to avoid disk reads every frame
- [x] GPU collection: called once per frame, result reused
- [x] hbar overflow protection: clamped to valid range
- [x] `_parse_window(None)`: returns default UsageWindow, doesn't crash
- [x] pyproject.toml: correct build backend
- [x] 190 tests passing
- [x] Pushed to `origin/dev/buddy`
