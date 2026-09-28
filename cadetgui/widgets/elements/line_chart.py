from __future__ import annotations

from typing import Any, Optional, Sequence

import anywidget
import traitlets as T

from ._assets import css, esm

__all__ = ["LineChart", "EventTimelineChart", "ChromatogramChart"]


class LineChart(anywidget.AnyWidget):
    """Interactive overlaid line chart: hover tooltip, drag-to-zoom, clickable legend.

    `series` is one entry per line: `{"name": str, "times": [minutes], "values": [float]}`,
    optionally `"dashed": bool` and `"reference": bool` (neutral measured-data color).
    Series may have different sample times. `x_name`/`x_unit` label the tooltip's x value.
    """

    series = T.List(T.Dict()).tag(sync=True)
    x_label = T.Unicode("Time / min").tag(sync=True)
    x_name = T.Unicode("t").tag(sync=True)
    x_unit = T.Unicode("min").tag(sync=True)
    y_label = T.Unicode("").tag(sync=True)
    empty_text = T.Unicode("No data").tag(sync=True)
    view_width = T.Int(480).tag(sync=True)
    view_height = T.Int(220).tag(sync=True)

    _esm = esm("line_chart", "_unit_parser")
    _css = css("line_chart")

    def __init__(
        self,
        *,
        series: Optional[Sequence[dict[str, Any]]] = None,
        **traits: Any,
    ) -> None:
        super().__init__(series=list(series or []), **traits)


class EventTimelineChart(LineChart):
    """Event timelines on one shared axis.

    `phases` (`{"name", "start", "end"}`, minutes) are drawn as alternating shaded bands;
    `markers` (`{"name", "time"}`, minutes) as labelled vertical lines.
    """

    phases = T.List(T.Dict()).tag(sync=True)
    markers = T.List(T.Dict()).tag(sync=True)
    y_label = T.Unicode("state").tag(sync=True)
    empty_text = T.Unicode("No events yet").tag(sync=True)


class ChromatogramChart(LineChart):
    """Simulated and optionally measured signals over time."""

    y_label = T.Unicode("Concentration").tag(sync=True)
    empty_text = T.Unicode("No solution to show").tag(sync=True)
    view_width = T.Int(720).tag(sync=True)
    view_height = T.Int(300).tag(sync=True)
