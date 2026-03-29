<!-- /autoplan restore point: /c/Users/Agam/.gstack/projects/agamarora-utils/dev-buddy-autoplan-restore-20260329-141838.md -->
# Plan: Hybrid JSONL + API Architecture for luna-monitor

## Problem

The Anthropic usage API (`api.anthropic.com/api/oauth/usage`) is undocumented and rate-limits aggressively. Both luna-monitor and Claude Pulse trigger a Cloudflare IP block with frequent polling. The burndown chart shows "Waiting for usage data..." indefinitely because no fresh API data arrives.

Claude Code locally stores all conversation data in JSONL files at `~/.claude/projects/**/*.jsonl`. These files contain per-message token usage and model info — available instantly, no API required.

## Goal

Build a **hybrid architecture**:
- **JSONL local collector** — always works, no API, reads `~/.claude/projects/**/*.jsonl`
- **API collector** — existing, rate-limited to 5 min intervals, provides session % and weekly %

The burndown waveform should use JSONL burn rate (tokens/min) instead of API utilization history.

## What to Build

### 1. `collectors/claude_local.py` (new file)

Reads JSONL files and computes:
- **5h window**: total tokens consumed in last 5 hours
- **7d window**: total tokens consumed in last 7 days
- **burn_rate**: tokens/min over the last 10 minutes (weighted)
- **model_breakdown**: `{model_name: token_count}` dict
- **burn_history**: deque of `(timestamp, burn_rate)` pairs for waveform

Token weighting (matches ccusage):
- `input_tokens` → 1.0x
- `cache_creation_input_tokens` → 1.0x (expensive)
- `cache_read_input_tokens` → 0.1x (cheap)
- `output_tokens` → 1.0x

JSONL structure confirmed from sampling (March 2026):
```json
{
  "timestamp": "2026-03-29T07:16:15.649Z",
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 3,
      "cache_creation_input_tokens": 9804,
      "cache_read_input_tokens": 11497,
      "output_tokens": 30,
      "service_tier": "standard"
    }
  }
}
```

**Critical implementation requirements (from review):**
1. **Subagent exclusion**: Filter out paths containing `/subagents/` — these represent sub-calls from parent sessions and would double-count tokens.
2. **Unicode handling**: Open files with `encoding='utf-8', errors='replace'` — confirmed real JSONL files contain non-UTF-8 chars.
3. **mtime filter**: Only open files modified within 7 days (check mtime before reading). 347 main JSONL files exist; reading all is too slow.
4. **Clock handling**: Timestamps have `Z` suffix — use `.replace("Z", "+00:00")` before `datetime.fromisoformat()`.
5. **Per-line error handling**: Try/except around each json.loads() — skip bad lines, continue.
6. **Cache TTL**: 2s in-memory cache so collect() is idempotent on the 2s refresh loop.
7. **Partial usage keys**: Use `.get(key, 0)` — some messages may omit certain token fields.

### 2. Update `panels/claude_burndown.py`

- New signature: accepts `LocalUsageData` (from claude_local) in addition to existing prediction
- Use `burn_history` deque for the waveform
- **Normalization**: burn_history stores raw tokens/min. Panel normalizes to 0-100 using `max(burn_history)` as denominator (auto-scales to session peak). If max == 0, all zeros (no divide-by-zero).
- Info line: show burn_rate in human-readable form (e.g., "12.3K tok/min") + model breakdown
- Fallback: if burn_history has < 2 points, show "Collecting local data..." (not "Waiting for usage data..." which was the API-blocked message)

### 3. Update `app.py`

- Import `claude_local` collector
- Call `claude_local.collect()` each frame — it's fast due to mtime filter + 2s cache
- Pass `LocalUsageData` to the burndown panel
- API collector (`fetch_usage`) continues unchanged — still provides % bars to status panel

## What NOT to Change

- `collectors/claude.py` — API collector, backoff logic unchanged
- System panels (CPU, memory, disk, network, processes)
- `claude_status.py` panel — still uses API data for % bars

## Architecture Diagram

```
~/.claude/projects/**/[session].jsonl   (excludes subagents/)
              │ (mtime filter: 7d)
              ▼
collectors/claude_local.py
  collect() → LocalUsageData
    ├── tokens_5h: int
    ├── tokens_7d: int
    ├── burn_rate: float        (tokens/min, last 10min)
    ├── model_breakdown: dict   {"claude-opus-4-6": 42, ...}
    └── burn_history: deque     [(timestamp, burn_rate), ...]
              │
              ├──────────────────────────┐
              ▼                          ▼
   panels/claude_burndown.py        app.py
   build_claude_burndown()          build_display()
   [normalizes burn_history          [calls both collectors,
    to 0-100, wave_chart()]          passes data to panels]
              │
              ▼
   ui/charts.py: wave_chart()       [expects 0-100 float values]
```

## Error & Rescue Registry

| Error | Where | Handling | User sees |
|-------|-------|----------|-----------|
| OSError: ~/.claude missing | glob | return empty LocalUsageData | "Collecting..." fallback |
| PermissionError per file | file open | skip file, continue | partial data |
| JSONDecodeError | json.loads | skip line, continue | partial data |
| UnicodeDecodeError | file read | errors='replace' prevents this | transparent |
| Missing usage keys | .get(k, 0) | default to 0 | transparent |
| Invalid timestamp | fromisoformat | skip line | transparent |
| burn_rate max=0 | normalize | return 0, no division | flat waveform |

## Failure Modes

| Failure | Risk | Mitigation |
|---------|------|------------|
| Subagent paths included | Med — double counts | Filter `subagents/` explicitly |
| Large files slow frame | Med — 347 files | mtime filter + 2s cache |
| Windows path differences | Med | Use Path.home() / pathlib |
| Model name changes | Low | Store raw model string, don't normalize |
| Clock skew | Low | Use UTC timestamps throughout |

## NOT in Scope

- Historical limit estimation (ccusage's "X% of max") — unknown limit, deferred
- JSONL-based session % bars — can't compute without knowing the plan limit
- Multi-machine aggregation — single-machine only
- ccusage validation script — manual step: `npx ccusage@latest blocks --since YYYYMMDD`

## What Already Exists (Reuse)

- `ui/charts.py:wave_chart()` — renders 0-100 float deque as waveform (confirmed API)
- `ui/charts.py:make_panel()` — panel wrapper with Claude border style
- `ui/colors.py:BURNDOWN_STYLE` — magenta style for Claude panels
- `collectors/claude.py:_usage_history` — parallel history for API utilization (unchanged)
- Test pattern: `mock_open`, `patch('pathlib.Path.glob')`, fixture deques

## Dream State Delta

```
CURRENT                 THIS PLAN               12-MONTH IDEAL
─────────────────────── ─────────────────────── ────────────────────────
Burndown broken (429)   Burndown always works   Multi-source fusion:
API is only source      JSONL = ground truth    JSONL + API + limits
"Waiting for data..."   Tokens/min waveform     ML-predicted "~2hr left"
No model breakdown      Opus/Sonnet/Haiku split Quota warning 30min early
```

## Verification

After implementation:
```bash
npx ccusage@latest blocks --since 20260329
```
Token totals should be within ~10% of what luna-monitor's burndown panel shows for today.

---

## Decision Audit Trail

<!-- AUTONOMOUS DECISION LOG -->

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Approach A (JSONL direct) | P1, P4 | Only pip-dep-free option, no coupling to external tools | B (ccusage subprocess), C (ccusage SQLite) |
| 2 | CEO | SELECTIVE EXPANSION mode | P3 | Plan scope is correct, no scope creep warranted | SCOPE EXPANSION |
| 3 | CEO | Add subagent exclusion requirement | P1 | Double-counting is a correctness bug, not a nice-to-have | Skip |
| 4 | CEO | Add unicode errors='replace' | P1 | Confirmed real JSONL files trigger UnicodeDecodeError | Silent crash |
| 5 | CEO | Add mtime filter for performance | P1 | 347 files, reading all on 2s tick is too slow | No filter |
| 6 | Eng | Burn rate normalization: session-max scaling | P5 | Explicit, self-calibrating, no arbitrary constants | Fixed scale |
| 7 | Eng | 2s cache TTL on collect() | P1 | Idempotent on 2s refresh loop | No cache |
| 8 | Eng | Per-line try/except in JSONL reader | P1 | Corrupted line must not crash the whole collector | Whole-file try |
| 9 | Eng | Test: 15 cases (P0: 10, P1: 5) | P1 | Full branch coverage at near-zero CC cost | Minimal tests |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | 5 issues found, all auto-decided |
| Design Review | skipped (no UI scope) | — | 0 | N/A | — |
| Eng Review | `/plan-eng-review` | Architecture & tests | 1 | clean | 4 gaps fixed in plan |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |

**VERDICT:** APPROVED (auto). 9 decisions, 0 taste decisions (all mechanical). Plan is ready for implementation.
