from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

import anywidget
import traitlets as T

from .._tokens import with_tokens

__all__ = ["LineChart", "EventTimelineChart", "ChromatogramChart"]

_DIR = Path(__file__).parent


class LineChart(anywidget.AnyWidget):
    """Interactive overlaid line chart: hover tooltip, drag-to-zoom, clickable legend.

    Display-only, not a form field, so it does not subclass `Element` (no
    value/validate/error contract to satisfy). `series` is JSON-safe data, one
    entry per line: `{"name": str, "times": [float, ...] (minutes),
    "values": [float, ...]}`, plus optional `"dashed": bool`, `"reference":
    bool` (drawn in the neutral measured-data color instead of a palette slot)
    and `"axis": "right"` (plots against the secondary y-axis, titled by
    `y_label_right`). Series may have different sample times. `x_name`/`x_unit`
    label the x value in the hover tooltip.
    """

    series = T.List(T.Dict()).tag(sync=True)
    x_label = T.Unicode("Time / min").tag(sync=True)
    x_name = T.Unicode("t").tag(sync=True)
    x_unit = T.Unicode("min").tag(sync=True)
    y_label = T.Unicode("").tag(sync=True)
    y_label_right = T.Unicode("").tag(sync=True)
    empty_text = T.Unicode("No data").tag(sync=True)
    view_width = T.Int(480).tag(sync=True)
    view_height = T.Int(220).tag(sync=True)

    _esm = _DIR / "line_chart.js"
    _css = with_tokens(_DIR / "line_chart.css")

    def __init__(
        self,
        *,
        series: Optional[Sequence[dict[str, Any]]] = None,
        **traits: Any,
    ) -> None:
        super().__init__(series=list(series) if series else [], **traits)


class EventTimelineChart(LineChart):
    """A process's event-driven parameter timelines, all on one shared axis."""

    y_label = T.Unicode("state").tag(sync=True)
    empty_text = T.Unicode("No events yet").tag(sync=True)


class ChromatogramChart(LineChart):
    """Simulated (and optionally measured) signals over time."""

    y_label = T.Unicode("Concentration").tag(sync=True)
    empty_text = T.Unicode("No solution to show").tag(sync=True)
    view_width = T.Int(720).tag(sync=True)
    view_height = T.Int(300).tag(sync=True)
