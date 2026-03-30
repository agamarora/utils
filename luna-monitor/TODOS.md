# TODOS

## Proxy crash recovery — wire up watchdog

**Priority:** High — README claims "if the proxy crashes, Claude Code falls back." This is currently false.

**Problem:** When the proxy crashes mid-session, `ANTHROPIC_BASE_URL` in `settings.json` still points at the dead port. Claude Code requests fail until luna-monitor is restarted or user runs `--disable-proxy`. The watchdog function exists (`proxy_lifecycle.rs:106`, `watchdog_tick`) but is `#[allow(dead_code)]` — never called.

**Fix:**
1. Call `watchdog_tick` in the main loop (app.rs) every tick
2. After 3 consecutive health check failures, restart proxy (already implemented)
3. If restart also fails, call `remove_proxy_setting()` so Claude Code falls back to direct API
4. Then the README claim becomes true

**Files:** `app.rs` (wire up call), `proxy_lifecycle.rs` (add settings removal on restart failure)
