# =========================================
# File: cadetgui/widgets/elements/event_timeline_chart.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

import anywidget
import traitlets as T

__all__ = ["EventTimelineChart"]

_DIR = Path(__file__).parent


class EventTimelineChart(anywidget.AnyWidget):
    """Interactive overlaid line chart of a process's event-driven parameter timelines.

    Display-only, not a form field, so it does not subclass `Element` (no
    value/validate/error contract to satisfy). `series` is JSON-safe data —
    values pulled directly from `Process.parameter_timelines`, not a rendered
    matplotlib figure — one entry per line: `{"name": str, "times": [float,
    ...], "values": [float, ...]}`. All series share one x/y axis, so callers
    should only pass series that are meaningfully on the same scale.
    """

    series = T.List(T.Dict()).tag(sync=True)
    x_label = T.Unicode("Time / min").tag(sync=True)
    y_label = T.Unicode("state").tag(sync=True)

    _esm = _DIR / "event_timeline_chart.js"
    _css = _DIR / "event_timeline_chart.css"

    def __init__(
        self,
        *,
        series: Optional[Sequence[dict[str, Any]]] = None,
        x_label: str = "Time / min",
        y_label: str = "state",
    ) -> None:
        super().__init__(series=list(series) if series else [], x_label=x_label, y_label=y_label)
