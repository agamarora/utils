"""Color threshold functions for system metrics."""


def pct_color(pct: float) -> str:
    """Color by percentage: cyan < 60 < yellow < 85 < red."""
    if pct >= 85:
        return "red"
    if pct >= 60:
        return "yellow"
    return "cyan"


def temp_color(celsius: float) -> str:
    """Color by temperature: green < 70 < yellow < 85 < red."""
    if celsius >= 85:
        return "red"
    if celsius >= 70:
        return "yellow"
    return "green"


def io_color(speed_bps: float) -> str:
    """Color I/O speed by intensity: dim < 1MB < cyan < 10MB < yellow < 100MB < red."""
    mb = speed_bps / 1e6
    if mb >= 100:
        return "red bold"
    if mb >= 10:
        return "yellow bold"
    if mb >= 1:
        return "cyan"
    return "dim"


# Claude panels use distinct colors to separate from system panels
CLAUDE_BORDER = "cyan"
SYSTEM_BORDER = "bright_black"
BURNDOWN_STYLE = "magenta"
CPU_STYLE = "cyan"
