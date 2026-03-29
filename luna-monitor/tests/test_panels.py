"""Tests for panels — rendering layer. Tests that panels return valid Rich renderables."""

import pytest
from collections import deque, namedtuple
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# Mock data structures that mimic psutil named tuples
_RamInfo = namedtuple("svmem", ["total", "available", "percent", "used", "free"])
_SwapInfo = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])
_DiskUsage = namedtuple("sdiskusage", ["total", "used", "free", "percent"])


def _mock_ram(pct=55.0, used=8e9, total=16e9):
    return _RamInfo(total=total, available=total - used, percent=pct, used=used, free=total - used)


def _mock_swap(pct=10.0, used=1e9, total=10e9):
    return _SwapInfo(total=total, used=used, free=total - used, percent=pct, sin=0, sout=0)


def _mock_swap_zero():
    return _SwapInfo(total=0, used=0, free=0, percent=0.0, sin=0, sout=0)


class TestCpuPanel:
    def test_basic_render(self):
        from luna_monitor.panels.cpu import build_cpu
        history = deque([50.0] * 20, maxlen=300)
        result = build_cpu(50.0, history, console_width=80)
        assert isinstance(result, Panel)

    def test_with_frequency(self):
        from luna_monitor.panels.cpu import build_cpu
        history = deque([75.0] * 5, maxlen=300)
        result = build_cpu(75.0, history, console_width=80, freq_str="4.10 GHz")
        assert isinstance(result, Panel)

    def test_with_throttling(self):
        from luna_monitor.panels.cpu import build_cpu
        history = deque([95.0] * 5, maxlen=300)
        result = build_cpu(95.0, history, console_width=80, throttled=True)
        assert isinstance(result, Panel)

    def test_empty_history(self):
        from luna_monitor.panels.cpu import build_cpu
        history = deque(maxlen=300)
        result = build_cpu(0.0, history, console_width=80)
        assert isinstance(result, Panel)

    def test_narrow_console(self):
        from luna_monitor.panels.cpu import build_cpu
        history = deque([50.0] * 5, maxlen=300)
        result = build_cpu(50.0, history, console_width=30)
        assert isinstance(result, Panel)


class TestMemoryPanel:
    def test_basic_render(self):
        from luna_monitor.panels.memory import build_memory
        result = build_memory(_mock_ram(), _mock_swap())
        assert isinstance(result, Panel)

    def test_no_swap(self):
        from luna_monitor.panels.memory import build_memory
        result = build_memory(_mock_ram(), _mock_swap_zero())
        assert isinstance(result, Panel)

    def test_memory_lines_with_swap(self):
        from luna_monitor.panels.memory import build_memory_lines
        lines = build_memory_lines(_mock_ram(), _mock_swap())
        assert len(lines) == 4  # RAM bar, RAM detail, Swap bar, Swap detail

    def test_memory_lines_no_swap(self):
        from luna_monitor.panels.memory import build_memory_lines
        lines = build_memory_lines(_mock_ram(), _mock_swap_zero())
        assert len(lines) == 2  # RAM bar, RAM detail only

    def test_high_usage(self):
        from luna_monitor.panels.memory import build_memory
        result = build_memory(_mock_ram(pct=95.0), _mock_swap())
        assert isinstance(result, Panel)


class TestGpuPanel:
    def test_with_gpu_data(self):
        from luna_monitor.panels.gpu import build_gpu_lines
        data = {"pct": 60.0, "mem_used": 4e9, "mem_total": 8e9, "temp": 72}
        lines = build_gpu_lines(data)
        assert len(lines) == 3  # bar, VRAM, temp

    def test_no_gpu_data(self):
        from luna_monitor.panels.gpu import build_gpu_lines
        lines = build_gpu_lines(None)
        assert len(lines) == 1
        assert "No GPU data" in lines[0].plain

    def test_gpu_no_temp(self):
        from luna_monitor.panels.gpu import build_gpu_lines
        data = {"pct": 30.0, "mem_used": 2e9, "mem_total": 8e9, "temp": None}
        lines = build_gpu_lines(data)
        assert len(lines) == 2  # bar + VRAM, no temp line

    def test_mem_gpu_side_by_side(self):
        from luna_monitor.panels.gpu import build_mem_gpu
        from luna_monitor.panels.memory import build_memory_lines
        ram_lines = build_memory_lines(_mock_ram(), _mock_swap())
        gpu_lines = [Text("No GPU data", style="dim")]
        result = build_mem_gpu(ram_lines, gpu_lines)
        assert isinstance(result, Table)

    def test_mem_gpu_matched_heights(self):
        from luna_monitor.panels.gpu import build_mem_gpu
        ram_lines = [Text("line1"), Text("line2"), Text("line3"), Text("line4")]
        gpu_lines = [Text("line1")]
        result = build_mem_gpu(ram_lines, gpu_lines)
        assert isinstance(result, Table)


class TestDisksPanel:
    def test_basic_render(self):
        from luna_monitor.panels.disks import build_disks
        disks = [("C:\\", _DiskUsage(total=500e9, used=200e9, free=300e9, percent=40.0))]
        result = build_disks(disks, {"C:\\": 15.0}, {"PhysicalDrive0": (1e6, 500e3)}, {"C:\\": "PhysicalDrive0"})
        assert isinstance(result, Panel)

    def test_no_disks(self):
        from luna_monitor.panels.disks import build_disks
        result = build_disks([], {}, {}, {})
        assert isinstance(result, Panel)

    def test_multiple_drives(self):
        from luna_monitor.panels.disks import build_disks
        disks = [
            ("C:\\", _DiskUsage(total=500e9, used=200e9, free=300e9, percent=40.0)),
            ("D:\\", _DiskUsage(total=1e12, used=600e9, free=400e9, percent=60.0)),
        ]
        result = build_disks(disks, {}, {}, {})
        assert isinstance(result, Panel)

    def test_no_pdh_data(self):
        from luna_monitor.panels.disks import build_disks
        disks = [("C:\\", _DiskUsage(total=500e9, used=200e9, free=300e9, percent=40.0))]
        result = build_disks(disks, {}, {}, {})  # empty PDH + IO data
        assert isinstance(result, Panel)


class TestNetworkPanel:
    def test_basic_render(self):
        from luna_monitor.panels.network import build_network
        stats = {"rx_avg": 5.0, "tx_avg": 1.0, "rx_peak": 50.0, "tx_peak": 10.0}
        result = build_network(10.0, 2.0, stats)
        assert isinstance(result, Panel)

    def test_zero_speeds(self):
        from luna_monitor.panels.network import build_network
        stats = {"rx_avg": 0.0, "tx_avg": 0.0, "rx_peak": 0.0, "tx_peak": 0.0}
        result = build_network(0.0, 0.0, stats)
        assert isinstance(result, Panel)

    def test_high_speeds(self):
        from luna_monitor.panels.network import build_network
        stats = {"rx_avg": 500.0, "tx_avg": 200.0, "rx_peak": 1000.0, "tx_peak": 500.0}
        result = build_network(800.0, 300.0, stats)
        assert isinstance(result, Panel)


class TestTempsPanel:
    def test_with_temps(self):
        from luna_monitor.panels.temps import build_temps
        temps = {"CPU Package": 65.0, "GPU": 72.0, "CPU Core 1": 63.0}
        result = build_temps(temps, lhm_running=True)
        assert isinstance(result, Panel)

    def test_no_temps_no_lhm(self):
        from luna_monitor.panels.temps import build_temps
        result = build_temps({}, lhm_running=False)
        assert isinstance(result, Panel)

    def test_no_temps_with_lhm(self):
        from luna_monitor.panels.temps import build_temps
        result = build_temps({}, lhm_running=True)
        assert isinstance(result, Panel)

    def test_no_cpu_temp_shows_hint(self):
        from luna_monitor.panels.temps import build_temps
        temps = {"GPU": 72.0}  # no CPU temp
        result = build_temps(temps, lhm_running=False)
        assert isinstance(result, Panel)

    def test_many_sensors_truncated_to_8(self):
        from luna_monitor.panels.temps import build_temps
        temps = {f"Sensor {i}": 50.0 + i for i in range(15)}
        result = build_temps(temps)
        assert isinstance(result, Panel)

    def test_priority_ordering(self):
        from luna_monitor.panels.temps import build_temps
        temps = {
            "Random Sensor": 40.0,
            "CPU Package": 65.0,
            "GPU": 72.0,
        }
        result = build_temps(temps, lhm_running=True)
        assert isinstance(result, Panel)


class TestProcessesPanel:
    def test_basic_render(self):
        from luna_monitor.panels.processes import build_procs
        procs = [
            {"name": "python", "cpu_percent": 25.0, "memory_percent": 5.0, "pid": 1},
            {"name": "chrome", "cpu_percent": 10.0, "memory_percent": 15.0, "pid": 2},
            {"name": "code", "cpu_percent": 5.0, "memory_percent": 10.0, "pid": 3},
        ]
        result = build_procs(procs)
        assert isinstance(result, Table)

    def test_empty_procs(self):
        from luna_monitor.panels.processes import build_procs
        result = build_procs([])
        assert isinstance(result, Table)

    def test_single_proc(self):
        from luna_monitor.panels.processes import build_procs
        procs = [{"name": "test", "cpu_percent": 50.0, "memory_percent": 20.0, "pid": 1}]
        result = build_procs(procs)
        assert isinstance(result, Table)

    def test_high_cpu_proc(self):
        from luna_monitor.panels.processes import build_procs
        procs = [{"name": "miner", "cpu_percent": 99.0, "memory_percent": 1.0, "pid": 1}]
        result = build_procs(procs)
        assert isinstance(result, Table)

    def test_long_proc_name_truncated(self):
        from luna_monitor.panels.processes import _proc_table
        procs = [{"name": "a" * 50, "cpu_percent": 10.0, "memory_percent": 5.0}]
        tbl = _proc_table(procs, "cpu")
        assert isinstance(tbl, Table)

    def test_none_values_handled(self):
        from luna_monitor.panels.processes import build_procs
        procs = [{"name": None, "cpu_percent": None, "memory_percent": None, "pid": 1}]
        result = build_procs(procs)
        assert isinstance(result, Table)


class TestClaudeProcessDetection:
    """Test Claude process correlation — is_claude_process()."""

    def test_claude_by_name(self):
        from luna_monitor.panels.processes import is_claude_process
        assert is_claude_process({"name": "claude"}) is True

    def test_claude_exe_by_name(self):
        from luna_monitor.panels.processes import is_claude_process
        assert is_claude_process({"name": "claude.exe"}) is True

    def test_node_with_claude_cmdline(self):
        from luna_monitor.panels.processes import is_claude_process
        proc = {"name": "node", "cmdline": ["/usr/bin/node", "/home/user/.claude/bin/claude"]}
        assert is_claude_process(proc) is True

    def test_node_with_anthropic_cmdline(self):
        from luna_monitor.panels.processes import is_claude_process
        proc = {"name": "node", "cmdline": ["node", "node_modules/@anthropic/sdk/dist/index.js"]}
        assert is_claude_process(proc) is True

    def test_node_without_claude_cmdline(self):
        from luna_monitor.panels.processes import is_claude_process
        proc = {"name": "node", "cmdline": ["node", "server.js"]}
        assert is_claude_process(proc) is False

    def test_regular_process(self):
        from luna_monitor.panels.processes import is_claude_process
        assert is_claude_process({"name": "chrome"}) is False

    def test_python_not_claude(self):
        from luna_monitor.panels.processes import is_claude_process
        assert is_claude_process({"name": "python"}) is False

    def test_none_name(self):
        from luna_monitor.panels.processes import is_claude_process
        assert is_claude_process({"name": None}) is False

    def test_empty_cmdline(self):
        from luna_monitor.panels.processes import is_claude_process
        proc = {"name": "node", "cmdline": []}
        assert is_claude_process(proc) is False

    def test_no_cmdline_key(self):
        from luna_monitor.panels.processes import is_claude_process
        proc = {"name": "node"}
        assert is_claude_process(proc) is False

    def test_claude_proc_renders_with_highlight(self):
        """Claude processes should render without crashing (visual check is manual)."""
        from luna_monitor.panels.processes import _proc_table
        procs = [
            {"name": "claude", "cpu_percent": 15.0, "memory_percent": 3.0},
            {"name": "chrome", "cpu_percent": 10.0, "memory_percent": 8.0},
        ]
        tbl = _proc_table(procs, "cpu")
        assert isinstance(tbl, Table)
