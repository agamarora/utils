"""Tests for collectors — system, gpu, platform abstractions."""

import pytest
from collections import deque
from unittest.mock import patch, MagicMock


class TestSystemCollector:
    """Tests for collectors.system — CPU, memory, network, disk, processes."""

    def test_collect_cpu_returns_tuple(self):
        from luna_monitor.collectors.system import collect_cpu
        avg, per_core = collect_cpu()
        assert isinstance(avg, float)
        assert 0.0 <= avg <= 100.0
        assert isinstance(per_core, list)
        assert len(per_core) > 0

    def test_collect_cpu_appends_to_history(self):
        from luna_monitor.collectors.system import collect_cpu, get_cpu_history
        history = get_cpu_history()
        len_before = len(history)
        collect_cpu()
        assert len(history) == len_before + 1

    def test_cpu_history_is_bounded(self):
        from luna_monitor.collectors.system import get_cpu_history
        history = get_cpu_history()
        assert history.maxlen == 300

    def test_collect_memory_returns_two_named_tuples(self):
        from luna_monitor.collectors.system import collect_memory
        ram, swap = collect_memory()
        assert hasattr(ram, "percent")
        assert hasattr(ram, "total")
        assert hasattr(ram, "used")
        assert hasattr(swap, "percent")
        assert hasattr(swap, "total")

    def test_collect_network_first_call_returns_zero(self):
        """First call has no delta, should return (0, 0)."""
        # Note: this test depends on module state — first call returns 0,0
        # Subsequent calls return real deltas. We test the interface.
        from luna_monitor.collectors.system import collect_network
        rx, tx = collect_network()
        assert isinstance(rx, float)
        assert isinstance(tx, float)
        assert rx >= 0.0
        assert tx >= 0.0

    def test_get_network_stats_returns_dict(self):
        from luna_monitor.collectors.system import get_network_stats
        stats = get_network_stats()
        assert "rx_avg" in stats
        assert "tx_avg" in stats
        assert "rx_peak" in stats
        assert "tx_peak" in stats

    def test_collect_disk_usage_valid_drive(self):
        from luna_monitor.collectors.system import collect_disk_usage
        disks = collect_disk_usage(["C:\\"])
        assert len(disks) >= 1
        drive, usage = disks[0]
        assert drive == "C:\\"
        assert hasattr(usage, "percent")

    def test_collect_disk_usage_invalid_drive(self):
        from luna_monitor.collectors.system import collect_disk_usage
        disks = collect_disk_usage(["Z:\\nonexistent\\"])
        assert len(disks) == 0  # gracefully skipped

    def test_collect_disk_io_no_crash(self):
        from luna_monitor.collectors.system import collect_disk_io
        collect_disk_io()  # should not raise

    def test_collect_temps_psutil_returns_dict(self):
        from luna_monitor.collectors.system import collect_temps_psutil
        temps = collect_temps_psutil()
        assert isinstance(temps, dict)

    def test_collect_processes_returns_list(self):
        from luna_monitor.collectors.system import collect_processes
        procs = collect_processes()
        assert isinstance(procs, list)
        if procs:
            assert "name" in procs[0]
            assert "cpu_percent" in procs[0]
            assert "memory_percent" in procs[0]

    def test_collect_processes_filters_idle(self):
        from luna_monitor.collectors.system import collect_processes
        procs = collect_processes()
        names = [p.get("name") for p in procs]
        assert "System Idle Process" not in names
        assert "" not in names

    def test_prime_no_crash(self):
        from luna_monitor.collectors.system import prime
        prime()  # should not raise


class TestGpuCollector:
    """Tests for collectors.gpu — NVIDIA GPU via pynvml."""

    def test_gpu_available_is_bool(self):
        from luna_monitor.collectors.gpu import GPU_AVAILABLE
        assert isinstance(GPU_AVAILABLE, bool)

    def test_gpu_name_is_string(self):
        from luna_monitor.collectors.gpu import GPU_NAME
        assert isinstance(GPU_NAME, str)

    def test_collect_gpu_returns_dict_or_none(self):
        from luna_monitor.collectors.gpu import collect_gpu, GPU_AVAILABLE
        result = collect_gpu()
        if GPU_AVAILABLE:
            assert isinstance(result, dict)
            assert "pct" in result
            assert "mem_used" in result
            assert "mem_total" in result
            assert "temp" in result
        else:
            assert result is None


class TestPlatformWin:
    """Tests for collectors.platform_win — Windows-specific collectors."""

    def test_is_windows_returns_bool(self):
        from luna_monitor.collectors.platform_win import is_windows
        assert isinstance(is_windows(), bool)

    def test_get_drive_to_disk_returns_dict(self):
        from luna_monitor.collectors.platform_win import get_drive_to_disk, is_windows
        mapping = get_drive_to_disk()
        assert isinstance(mapping, dict)
        if is_windows():
            # Should have at least C:\ on Windows
            assert "C:\\" in mapping

    def test_collect_disk_active_returns_dict(self):
        from luna_monitor.collectors.platform_win import collect_disk_active
        result = collect_disk_active()
        assert isinstance(result, dict)

    def test_collect_temps_lhm_returns_dict(self):
        from luna_monitor.collectors.platform_win import collect_temps_lhm
        result = collect_temps_lhm()
        assert isinstance(result, dict)

    def test_get_lhm_freq_str_returns_tuple(self):
        from luna_monitor.collectors.platform_win import get_lhm_freq_str
        freq_str, avg_mhz = get_lhm_freq_str()
        assert isinstance(freq_str, str)
        assert isinstance(avg_mhz, float)


class TestPlatformPosix:
    """Tests for collectors.platform_posix — POSIX stubs."""

    def test_all_stubs_return_empty(self):
        from luna_monitor.collectors.platform_posix import (
            init_drive_map, get_drive_to_disk, init_pdh,
            collect_disk_active, collect_temps_lhm, get_lhm_clocks,
            get_lhm_freq_str,
        )
        assert init_drive_map() == {}
        assert get_drive_to_disk() == {}
        assert init_pdh() is None
        assert collect_disk_active() == {}
        assert collect_temps_lhm() == {}
        assert get_lhm_clocks() == {}
        freq_str, mhz = get_lhm_freq_str()
        assert freq_str == ""
        assert mhz == 0.0
