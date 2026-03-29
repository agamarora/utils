"""Tests for the local JSONL collector and updated burndown panel.

Uses tmp_path (real temp directories) rather than mock_open — this is more
reliable for testing glob-based file scanning. Each test writes real JSONL
files and patches CLAUDE_PROJECTS_DIR to the temp dir.
"""

import json
import time
import pytest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import luna_monitor.collectors.claude_local as _local_mod
from luna_monitor.collectors.claude_local import (
    LocalUsageData,
    collect,
    get_burn_history,
    model_short,
    fmt_tokens,
    fmt_rate,
    _weighted_tokens,
    _parse_ts,
    _scan_files,
)
from luna_monitor.panels.claude_burndown import build_claude_burndown


# ── Helpers ──────────────────────────────────────────────────

def _make_entry(ts_iso: str, model: str, **usage_kwargs) -> str:
    """Build a JSONL line as a string."""
    usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    usage.update(usage_kwargs)
    entry = {
        "timestamp": ts_iso,
        "message": {
            "model": model,
            "usage": usage,
        },
    }
    return json.dumps(entry)


def _now_iso() -> str:
    """ISO timestamp for right now (UTC, with Z suffix)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _ago_iso(seconds: float) -> str:
    """ISO timestamp for N seconds ago (UTC, with Z suffix)."""
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level cache and burn history before each test."""
    _local_mod._cached = None
    _local_mod._cached_at = 0.0
    _local_mod._burn_history.clear()
    yield
    _local_mod._cached = None
    _local_mod._cached_at = 0.0
    _local_mod._burn_history.clear()


# ── Token weighting ──────────────────────────────────────────

class TestWeightedTokens:
    def test_input_tokens_full_weight(self):
        assert _weighted_tokens({"input_tokens": 100}) == 100.0

    def test_cache_creation_full_weight(self):
        assert _weighted_tokens({"cache_creation_input_tokens": 200}) == 200.0

    def test_cache_read_zero_weight(self):
        # cache_read excluded — re-reads of existing context, not new consumption
        assert _weighted_tokens({"cache_read_input_tokens": 1000}) == pytest.approx(0.0)

    def test_output_full_weight(self):
        assert _weighted_tokens({"output_tokens": 50}) == 50.0

    def test_combined_weighting(self):
        result = _weighted_tokens({
            "input_tokens": 100,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 1000,
            "output_tokens": 50,
        })
        # 100*1 + 200*1 + 1000*0.0 + 50*1 = 100+200+0+50 = 350
        assert result == pytest.approx(350.0)

    def test_missing_keys_default_to_zero(self):
        assert _weighted_tokens({}) == 0.0

    def test_partial_keys(self):
        assert _weighted_tokens({"input_tokens": 10, "output_tokens": 5}) == 15.0


# ── Timestamp parsing ────────────────────────────────────────

class TestParseTs:
    def test_z_suffix(self):
        ts = _parse_ts("2026-03-29T07:16:15.649Z")
        assert ts is not None
        assert ts > 0

    def test_offset_format(self):
        ts = _parse_ts("2026-03-29T07:16:15+00:00")
        assert ts is not None

    def test_invalid_returns_none(self):
        assert _parse_ts("not-a-date") is None

    def test_none_input(self):
        assert _parse_ts(None) is None  # type: ignore

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_z_and_offset_equivalent(self):
        ts_z = _parse_ts("2026-03-29T07:00:00.000Z")
        ts_off = _parse_ts("2026-03-29T07:00:00+00:00")
        assert ts_z == pytest.approx(ts_off)


# ── Format helpers ───────────────────────────────────────────

class TestFmtTokens:
    def test_millions(self):
        assert fmt_tokens(1_234_567) == "1.2M"

    def test_thousands(self):
        assert fmt_tokens(12_345) == "12.3K"

    def test_small(self):
        assert fmt_tokens(42) == "42"

    def test_exactly_one_million(self):
        assert "M" in fmt_tokens(1_000_000)


class TestFmtRate:
    def test_includes_tok_per_min(self):
        assert "tok/min" in fmt_rate(5000.0)


class TestModelShort:
    def test_opus(self):
        assert model_short("claude-opus-4-6") == "Opus"

    def test_sonnet(self):
        assert model_short("claude-sonnet-4-6") == "Sonnet"

    def test_haiku(self):
        assert model_short("claude-haiku-4-5-20251001") == "Haiku"

    def test_unknown_passthrough(self):
        result = model_short("some-future-model")
        assert result == "some-future-model"


# ── File scanning (P0 test cases) ────────────────────────────

class TestCollectEmptyStates:
    def test_no_projects_dir(self, tmp_path):
        """Missing ~/.claude/projects → empty LocalUsageData, no crash."""
        missing = tmp_path / "nonexistent"
        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", missing):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 0
        assert result.tokens_7d == 0
        assert result.burn_rate == 0.0
        assert result.model_breakdown == {}

    def test_empty_dir(self, tmp_path):
        """Projects dir exists but has no JSONL files → empty result."""
        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 0
        assert result.tokens_7d == 0


class TestSubagentExclusion:
    def test_subagent_files_excluded(self, tmp_path):
        """Files under subagents/ directory are NOT counted."""
        # Create a subagent file with real tokens
        subdir = tmp_path / "session-abc" / "subagents"
        subdir.mkdir(parents=True)
        f = subdir / "agent-xyz.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=1000))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 0  # subagent not counted

    def test_main_session_counted(self, tmp_path):
        """Main session files (not in subagents/) are counted."""
        f = tmp_path / "session-abc.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 100

    def test_mixed_subagent_and_main(self, tmp_path):
        """Only main session tokens counted when both types present."""
        # Main session
        main = tmp_path / "session-main.jsonl"
        main.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        # Subagent file — should be excluded
        subdir = tmp_path / "session-main" / "subagents"
        subdir.mkdir(parents=True)
        sub = subdir / "agent-1.jsonl"
        sub.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=500))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 100  # only main session


class TestErrorHandling:
    def test_bad_json_line_skipped(self, tmp_path):
        """JSONDecodeError on a line skips that line, rest of file processed."""
        f = tmp_path / "session.jsonl"
        lines = [
            "INVALID JSON LINE",
            _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 100  # good line still counted

    def test_empty_lines_skipped(self, tmp_path):
        """Empty lines in JSONL don't crash the parser."""
        f = tmp_path / "session.jsonl"
        lines = [
            "",
            _make_entry(_now_iso(), "claude-sonnet-4-6", input_tokens=50),
            "",
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 50

    def test_missing_message_key_skipped(self, tmp_path):
        """Lines without 'message' key are skipped gracefully."""
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"timestamp": _now_iso(), "type": "system"}),  # no message
            _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 100

    def test_missing_usage_key_skipped(self, tmp_path):
        """Messages without 'usage' (e.g., user messages) are skipped."""
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"timestamp": _now_iso(), "message": {"role": "user", "content": "hi"}}),
            _make_entry(_now_iso(), "claude-opus-4-6", output_tokens=30),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 30

    def test_permission_error_on_file_skipped(self, tmp_path):
        """PermissionError on a file skips it, doesn't crash the collector."""
        f = tmp_path / "unreadable.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        original_read_file = _local_mod._read_file

        def raise_perm(path, cutoff, messages, seen_keys):
            if path.name == "unreadable.jsonl":
                raise PermissionError("no access")
            return original_read_file(path, cutoff, messages, seen_keys)

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            with patch.object(_local_mod, "_read_file", side_effect=raise_perm):
                result = collect(cache_ttl=0)
        assert result.tokens_5h == 0  # unreadable file skipped


class TestTimeWindows:
    def test_5h_window_includes_recent(self, tmp_path):
        """Messages within last 5 hours appear in tokens_5h."""
        f = tmp_path / "session.jsonl"
        lines = [
            _make_entry(_ago_iso(3600), "claude-opus-4-6", input_tokens=100),  # 1h ago
            _make_entry(_ago_iso(4 * 3600), "claude-opus-4-6", input_tokens=200),  # 4h ago
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 300

    def test_5h_window_excludes_old(self, tmp_path):
        """Messages older than 5h are NOT in tokens_5h but are in tokens_7d."""
        f = tmp_path / "session.jsonl"
        lines = [
            _make_entry(_ago_iso(2 * 3600), "claude-opus-4-6", input_tokens=100),  # 2h ago → in 5h
            _make_entry(_ago_iso(6 * 3600), "claude-opus-4-6", input_tokens=200),  # 6h ago → NOT in 5h
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 100
        assert result.tokens_7d == 300

    def test_7d_window_includes_week_old(self, tmp_path):
        """Messages up to 7 days old appear in tokens_7d."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            _make_entry(_ago_iso(6 * 86400), "claude-sonnet-4-6", input_tokens=500)  # 6 days ago
        )
        # Make the file itself appear recent so mtime filter doesn't block it
        import os
        os.utime(f, None)  # touch file

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_7d == 500
        assert result.tokens_5h == 0  # but not in 5h window


class TestBurnRate:
    def test_burn_rate_zero_when_no_recent_messages(self, tmp_path):
        """No messages in last 10 min → burn_rate = 0."""
        f = tmp_path / "session.jsonl"
        # Message from 20 minutes ago
        f.write_text(_make_entry(_ago_iso(20 * 60), "claude-opus-4-6", input_tokens=1000))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.burn_rate == 0.0

    def test_burn_rate_computed_over_10min_window(self, tmp_path):
        """Tokens in last 10min / 10 = burn_rate."""
        f = tmp_path / "session.jsonl"
        # 600 input tokens from 5 minutes ago
        f.write_text(_make_entry(_ago_iso(5 * 60), "claude-opus-4-6", input_tokens=600))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        # 600 tokens / 10 min = 60 tok/min
        assert result.burn_rate == pytest.approx(60.0)

    def test_cache_read_excluded_from_burn_rate(self, tmp_path):
        """cache_read_input_tokens are 0-weighted — don't contribute to burn rate."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            _make_entry(_ago_iso(60), "claude-opus-4-6", cache_read_input_tokens=1000)
        )

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        # 1000 * 0.0 = 0 weighted tokens → burn_rate = 0
        assert result.burn_rate == pytest.approx(0.0)


class TestStreamingDeduplication:
    """Claude Code logs streaming responses multiple times (same requestId+messageId).
    We must deduplicate to match ccusage and avoid 1.75x+ over-counting."""

    def test_duplicate_request_id_counted_once(self, tmp_path):
        """Same requestId+messageId appearing multiple times → counted once."""
        f = tmp_path / "session.jsonl"
        entry_partial = json.dumps({
            "timestamp": _now_iso(),
            "requestId": "req_abc123",
            "message": {
                "id": "msg_xyz789",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 100_000,
                          "cache_creation_input_tokens": 0, "output_tokens": 10},
            },
        })
        entry_final = json.dumps({
            "timestamp": _now_iso(),
            "requestId": "req_abc123",
            "message": {
                "id": "msg_xyz789",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 5, "cache_read_input_tokens": 100_000,
                          "cache_creation_input_tokens": 0, "output_tokens": 500},
            },
        })
        # Write the same request twice (partial then final, as Claude Code does during streaming)
        f.write_text(entry_partial + "\n" + entry_final)

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)

        # Should count only FIRST occurrence: 5 + 100_000*0.0 + 10 = 15 weighted
        # (cache_read excluded at 0.0x; output=10 from first occurrence, not 500)
        expected = 5 + 100_000 * 0.0 + 10
        assert result.tokens_5h == int(expected)

    def test_no_ids_not_deduplicated(self, tmp_path):
        """Entries without requestId or messageId are never deduplicated (safe fallback)."""
        f = tmp_path / "session.jsonl"
        lines = [
            _make_entry(_now_iso(), "claude-sonnet-4-6", input_tokens=100),
            _make_entry(_now_iso(), "claude-sonnet-4-6", input_tokens=100),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        # Both entries counted (no ids → no dedup key → both pass)
        assert result.tokens_5h == 200

    def test_different_request_ids_both_counted(self, tmp_path):
        """Two distinct requests are both counted even if close in time."""
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"timestamp": _now_iso(), "requestId": "req_aaa",
                        "message": {"id": "msg_aaa", "model": "claude-opus-4-6",
                                    "usage": {"input_tokens": 100, "output_tokens": 0,
                                              "cache_creation_input_tokens": 0,
                                              "cache_read_input_tokens": 0}}}),
            json.dumps({"timestamp": _now_iso(), "requestId": "req_bbb",
                        "message": {"id": "msg_bbb", "model": "claude-opus-4-6",
                                    "usage": {"input_tokens": 200, "output_tokens": 0,
                                              "cache_creation_input_tokens": 0,
                                              "cache_read_input_tokens": 0}}}),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 300  # 100 + 200, both counted

    def test_cross_file_dedup(self, tmp_path):
        """Same requestId+messageId in two different session files → counted once."""
        entry = json.dumps({
            "timestamp": _now_iso(),
            "requestId": "req_shared",
            "message": {
                "id": "msg_shared",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 500, "output_tokens": 0,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        })
        (tmp_path / "session_a.jsonl").write_text(entry)
        (tmp_path / "session_b.jsonl").write_text(entry)

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_5h == 500  # counted once, not twice


class TestModelBreakdown:
    def test_single_model(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert "claude-opus-4-6" in result.model_breakdown
        assert result.model_breakdown["claude-opus-4-6"] == 100

    def test_multiple_models(self, tmp_path):
        f = tmp_path / "session.jsonl"
        lines = [
            _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100),
            _make_entry(_now_iso(), "claude-sonnet-4-6", input_tokens=200),
            _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=50),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.model_breakdown["claude-opus-4-6"] == 150  # 100+50
        assert result.model_breakdown["claude-sonnet-4-6"] == 200

    def test_unknown_model_still_counted(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-future-99", input_tokens=300))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.model_breakdown.get("claude-future-99", 0) == 300


class TestMtimeFilter:
    def test_old_files_skipped_by_mtime(self, tmp_path):
        """Files with mtime older than 7d are not opened."""
        import os
        f = tmp_path / "old.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=999))
        # Set mtime to 8 days ago
        old_time = time.time() - 8 * 86400
        os.utime(f, (old_time, old_time))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.tokens_7d == 0  # file was not opened


class TestCacheTTL:
    def test_cache_returns_same_result(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            r1 = collect(cache_ttl=60)
            # Modify file — cache should still return first result
            f.write_text(
                "\n".join([
                    _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100),
                    _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=999),
                ])
            )
            r2 = collect(cache_ttl=60)
        assert r1 is r2  # same object

    def test_cache_bypass_on_ttl_zero(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            r1 = collect(cache_ttl=0)
            f.write_text(
                "\n".join([
                    _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100),
                    _make_entry(_now_iso(), "claude-opus-4-6", input_tokens=200),
                ])
            )
            r2 = collect(cache_ttl=0)
        assert r1 is not r2  # fresh scan


class TestBurnHistory:
    def test_burn_history_appended_on_collect(self, tmp_path):
        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            collect(cache_ttl=0)
        history = get_burn_history()
        assert len(history) == 1
        ts, rate = history[0]
        assert isinstance(ts, float)
        assert rate == 0.0  # no files → zero burn

    def test_burn_history_grows_over_time(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(_make_entry(_now_iso(), "claude-opus-4-6", input_tokens=100))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            collect(cache_ttl=0)
            collect(cache_ttl=0)
        # Two collects (cache_ttl=0 forces re-scan)
        history = get_burn_history()
        assert len(history) == 2


# ── Burndown panel ───────────────────────────────────────────

class TestBuildClaudeBurndown:
    def test_empty_history_shows_collecting(self):
        """< 2 data points → 'Collecting local data...' placeholder."""
        local_data = LocalUsageData()
        history = deque(maxlen=300)
        panel = build_claude_burndown(local_data, history, console_width=120)
        from rich.panel import Panel
        assert isinstance(panel, Panel)
        # Panel title should be "Claude Activity"
        assert "Claude Activity" in str(panel.title)

    def test_single_point_shows_collecting(self):
        local_data = LocalUsageData()
        history = deque([(time.time(), 100.0)], maxlen=300)
        panel = build_claude_burndown(local_data, history, console_width=120)
        from rich.panel import Panel
        assert isinstance(panel, Panel)

    def test_sufficient_history_renders_waveform(self):
        """2+ data points → waveform rendered."""
        local_data = LocalUsageData(burn_rate=5000.0)
        history = deque(
            [(time.time() - i, float(i * 100)) for i in range(10)],
            maxlen=300,
        )
        panel = build_claude_burndown(local_data, history, console_width=120)
        from rich.panel import Panel
        assert isinstance(panel, Panel)

    def test_zero_max_no_divide_by_zero(self):
        """All-zero burn history must not raise ZeroDivisionError."""
        local_data = LocalUsageData(burn_rate=0.0)
        history = deque(
            [(time.time() - i, 0.0) for i in range(5)],
            maxlen=300,
        )
        panel = build_claude_burndown(local_data, history, console_width=120)
        from rich.panel import Panel
        assert isinstance(panel, Panel)  # no exception

    def test_title_is_always_claude_activity(self):
        """Title is always 'Claude Activity' — no % duplication with Status panel."""
        local_data = LocalUsageData(burn_rate=0.0)
        history = deque(
            [(time.time() - i, float(i)) for i in range(5)],
            maxlen=300,
        )
        panel = build_claude_burndown(local_data, history, console_width=120)
        assert "Claude Activity" in str(panel.title)
        assert "used" not in str(panel.title)  # never shows % in title


class TestRequestCount:
    def test_requests_5h_counted(self, tmp_path):
        """requests_5h counts deduped API calls in the 5h window."""
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"timestamp": _now_iso(), "requestId": "req_1",
                        "message": {"id": "msg_1", "model": "claude-opus-4-6",
                                    "usage": {"input_tokens": 10, "output_tokens": 5,
                                              "cache_creation_input_tokens": 0,
                                              "cache_read_input_tokens": 0}}}),
            json.dumps({"timestamp": _now_iso(), "requestId": "req_2",
                        "message": {"id": "msg_2", "model": "claude-opus-4-6",
                                    "usage": {"input_tokens": 20, "output_tokens": 8,
                                              "cache_creation_input_tokens": 0,
                                              "cache_read_input_tokens": 0}}}),
        ]
        f.write_text("\n".join(lines))

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.requests_5h == 2

    def test_duplicate_requests_counted_once(self, tmp_path):
        """Streaming duplicates don't inflate requests_5h."""
        entry = json.dumps({"timestamp": _now_iso(), "requestId": "req_dup",
                            "message": {"id": "msg_dup", "model": "claude-sonnet-4-6",
                                        "usage": {"input_tokens": 5, "output_tokens": 50,
                                                  "cache_creation_input_tokens": 0,
                                                  "cache_read_input_tokens": 0}}})
        f = tmp_path / "session.jsonl"
        f.write_text(entry + "\n" + entry)  # same request twice

        with patch.object(_local_mod, "CLAUDE_PROJECTS_DIR", tmp_path):
            result = collect(cache_ttl=0)
        assert result.requests_5h == 1  # deduped to one
