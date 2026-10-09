from __future__ import annotations

import html
from typing import Any

import ipywidgets as W
import numpy as np

from .._chrome import style_tag
from ..elements import EventTimelineChart
from ._timeline_data import timeline_chart_data

__all__ = ["EventsWidget"]


def _state(value: Any) -> str:
    return repr(value.tolist() if isinstance(value, np.ndarray) else value)


def events_table_html(process: Any) -> str:
    """Table of a process's events: name, time, parameter path and state."""
    if not process.events:
        return "<em>This process has no events.</em>"
    rows = "".join(
        f"<tr><td>{html.escape(e.name)}</td><td>{e.time:g}</td>"
        f"<td><code>{html.escape(e.parameter_path)}</code></td>"
        f"<td><code>{html.escape(_state(e.state))}</code></td></tr>"
        for e in sorted(process.events, key=lambda e: e.time)
    )
    return (
        "<table class='cadetgui-table'><thead><tr><th>Event</th><th>Time / s</th>"
        f"<th>Parameter</th><th>State</th></tr></thead><tbody>{rows}</tbody></table>"
    )


class EventsWidget:
    """The events of a CADET-Process Process, as a table and as parameter timelines."""

    def __init__(self, process: Any) -> None:
        self.process = process
        self.chart = EventTimelineChart()
        self._table = W.HTML()
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Events of {title}</div>"),
            self._table,
            self.chart,
        ])
        self.root.add_class("cadetgui-panel")
        self.refresh()

    def refresh(self) -> None:
        """Redraw, e.g. after events were added or the cycle time changed in code."""
        self._table.value = events_table_html(self.process)
        data = timeline_chart_data(self.process, self.process.component_system.names, ())
        if data is None:
            self.chart.series = []
            return
        self.chart.y_label = data["y_label"]
        self.chart.phases = data["phases"]
        self.chart.markers = data["markers"]
        self.chart.series = data["series"]

    def get_value(self) -> Any:
        """Return the Process this widget shows."""
        return self.process

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
