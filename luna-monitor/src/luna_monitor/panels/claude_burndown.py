"""Claude Burndown panel — usage waveform with prediction.

The killer feature: a time-series chart of Claude usage consumption
with a projected time-to-limit. Dynamic title shows "~X min remaining (estimated)".
Uses magenta waveform to visually distinguish from the cyan CPU chart.
"""

from collections import deque

from rich.console import Group
from rich.text import Text

from luna_monitor.collectors.claude import BurndownPrediction
from luna_monitor.ui.charts import wave_chart, make_panel
from luna_monitor.ui.colors import BURNDOWN_STYLE


def build_claude_burndown(
    usage_history: deque,
    prediction: BurndownPrediction,
    console_width: int,
) -> object:
    """Build the Claude Burndown panel.

    Args:
        usage_history: Deque of (timestamp, utilization) pairs.
        prediction: BurndownPrediction from predict_burndown().
        console_width: Terminal width for chart sizing.
    """
    # Utilization is already 0-100 from the API — use directly
    pct_history = deque(
        (u for _, u in usage_history),
        maxlen=usage_history.maxlen or 300,
    )

    if len(pct_history) < 2:
        return make_panel(
            Text("Waiting for usage data...", style="dim italic"),
            "Usage Burndown",
            claude=True,
        )

    chart = wave_chart(pct_history, console_width, height=5, style=BURNDOWN_STYLE)

    # Dynamic title based on prediction
    title = f"Usage Burndown — {prediction.label}"

    # Info line under chart
    info = Text()
    if prediction.confidence == "high":
        info.append(prediction.label, style="magenta bold")
    elif prediction.confidence == "medium":
        info.append(prediction.label, style="magenta")
    else:
        info.append(prediction.label, style="dim")

    return make_panel(Group(*chart, info), title, claude=True)
