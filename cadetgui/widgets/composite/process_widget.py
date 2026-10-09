from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Tuple

import ipywidgets as W
import numpy as np

from ...parameters import describe_parameter
from .._chrome import style_tag
from ..elements import EventTimelineChart, TextField
from ._parameter_values import (
    assign_literal,
    format_value,
    parameter_names,
    parameter_owners,
)
from ._timeline_data import timeline_chart_data

__all__ = ["ProcessWidget", "events_table_html"]


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


def _heading(text: str) -> W.HTML:
    return W.HTML(f"<div class='cadetgui-section-title'><code>{html.escape(text)}</code></div>")


class ProcessWidget:
    """Configure a CADET-Process Process: cycle time, unit parameters by path, and events.

    Every parameter below the process is listed under its path, e.g.
    `flow_sheet.column.length`. Parameters that events change are locked.
    """

    def __init__(self, process: Any) -> None:
        self.process = process
        self._listeners: List[Callable[[Any], None]] = []
        self.fields: Dict[str, TextField] = {}
        self._owners: Dict[str, Tuple[Any, str]] = {}
        self._parameters = W.VBox()
        self._events_table = W.HTML()
        self.chart = EventTimelineChart()
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Process · {title}</div>"),
            self._parameters,
            W.HTML("<div class='cadetgui-section-title'>Events</div>"),
            self._events_table,
            self.chart,
        ])
        self.root.add_class("cadetgui-panel")
        self.refresh()

    def refresh(self) -> None:
        """Rebuild from the process, e.g. after units or events were added in code."""
        self.fields = {}
        self._owners = {}
        children = [_heading("process")]
        children += self._group(self.process, "", ["cycle_time"])
        for prefix, owner in parameter_owners(self.process):
            children.append(_heading(prefix))
            children += self._group(owner, f"{prefix}.", parameter_names(owner))
        self._parameters.children = children
        self._refresh_events()

    def _group(self, owner: Any, prefix: str, names: List[str]) -> List[W.Widget]:
        locked = set(self.process.event_parameters)
        widgets: List[W.Widget] = []
        locked_here = []
        for name in names:
            path = f"{prefix}{name}"
            unit, _description = describe_parameter(owner, name)
            field = TextField(label=name, value=format_value(owner, name), units=unit)
            if path in locked:
                field.disabled = True
                locked_here.append(name)
            field.observe(lambda change, path=path: self._on_edit(path, change), names="value")
            self.fields[path] = field
            self._owners[path] = (owner, name)
            widgets.append(field)
        if locked_here:
            note = f"Set by events: {', '.join(locked_here)}"
            widgets.append(W.HTML(f"<small>{html.escape(note)}</small>"))
        return widgets

    def _on_edit(self, path: str, change: dict) -> None:
        owner, name = self._owners[path]
        field = self.fields[path]
        text = change["new"].strip()
        if not text or text == format_value(owner, name):
            return
        error = assign_literal(owner, name, text)
        field.error = error or ""
        if error:
            return
        for other, other_field in self.fields.items():
            other_field.value = format_value(*self._owners[other])
        self._refresh_events()
        for fn in list(self._listeners):
            fn(self.process)

    def _refresh_events(self) -> None:
        self._events_table.value = events_table_html(self.process)
        data = timeline_chart_data(self.process, self.process.component_system.names, ())
        if data is None:
            self.chart.series = []
            return
        self.chart.y_label = data["y_label"]
        self.chart.phases = data["phases"]
        self.chart.markers = data["markers"]
        self.chart.series = data["series"]

    def get_value(self) -> Any:
        """Return the Process this widget configures."""
        return self.process

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(process)` after every accepted edit."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
