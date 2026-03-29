"""Processes panel: top processes by CPU and RAM usage, side-by-side.

Claude-related processes are highlighted with a distinct cyan color
so you can see at a glance what Claude Code is doing to your system.
"""

from rich.table import Table
from rich.text import Text

from luna_monitor.ui.charts import make_panel

PROC_COUNT = 6

# Process names and command-line patterns that indicate Claude Code activity
_CLAUDE_PROCESS_NAMES = {"claude", "claude.exe"}
_CLAUDE_CMD_PATTERNS = {"claude", "@anthropic"}


def is_claude_process(proc: dict) -> bool:
    """Check if a process is related to Claude Code.

    Matches by process name or command-line arguments containing
    claude/@anthropic patterns. For node processes, fetches cmdline
    lazily via psutil to avoid the cost of reading every process's
    command line on every refresh cycle.
    """
    name = (proc.get("name") or "").lower()
    if name in _CLAUDE_PROCESS_NAMES:
        return True
    # node processes running Claude Code — fetch cmdline lazily
    if name in ("node", "node.exe"):
        cmdline = proc.get("cmdline")
        if cmdline is None:
            # Lazy fetch: try to get cmdline from psutil by PID
            pid = proc.get("pid")
            if pid:
                try:
                    import psutil
                    p = psutil.Process(pid)
                    cmdline = p.cmdline()
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    cmdline = []
            else:
                cmdline = []
        if isinstance(cmdline, list):
            cmd_str = " ".join(cmdline).lower()
        else:
            cmd_str = str(cmdline).lower()
        return any(pat in cmd_str for pat in _CLAUDE_CMD_PATTERNS)
    return False


def _proc_table(procs: list[dict], highlight: str) -> Table:
    """Build a process table. highlight='cpu' or 'ram'."""
    tbl = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column(ratio=3, no_wrap=True)
    tbl.add_column(width=7, justify="right")
    for p in procs:
        name = (p.get("name") or "")[:24]
        claude = is_claude_process(p)

        if highlight == "cpu":
            val = p.get("cpu_percent") or 0.0
            style = "red" if val > 30 else ("yellow" if val > 10 else "white")
        else:
            val = p.get("memory_percent") or 0.0
            style = "red" if val > 20 else ("yellow" if val > 10 else "white")

        # Claude processes get cyan name to stand out
        name_style = "cyan bold" if claude else "white"
        tbl.add_row(Text(name, style=name_style), Text(f"{val:.1f}%", style=style))
    return tbl


def build_procs(all_procs: list[dict], proc_count: int = PROC_COUNT) -> Table:
    """Build side-by-side process panels (CPU + RAM).

    Args:
        all_procs: List of process info dicts from collect_processes().
        proc_count: Number of processes to show per column.
    """
    by_cpu = sorted(
        all_procs, key=lambda x: x.get("cpu_percent") or 0, reverse=True
    )[:proc_count]
    by_ram = sorted(
        all_procs, key=lambda x: x.get("memory_percent") or 0, reverse=True
    )[:proc_count]

    side = Table(box=None, padding=0, show_header=False, expand=True)
    side.add_column(ratio=1)
    side.add_column(ratio=1)
    side.add_row(
        make_panel(_proc_table(by_cpu, "cpu"), "Processes (CPU)"),
        make_panel(_proc_table(by_ram, "ram"), "Processes (RAM)"),
    )
    return side
