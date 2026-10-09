from __future__ import annotations

import html
import math
from typing import Any, Callable, List, Mapping, Optional

import ipywidgets as W
import numpy as np
from CADETProcess.processModel import FlowSheet, Process

from .._chrome import style_tag
from ..elements import EventTimelineChart, TextField
from ._code_view import CodeView
from ._parameter_values import (
    assign_literal,
    code_literal,
    components_html,
    format_value,
    parameter_names,
    parameter_owners,
    set_by_path,
    value_html,
)
from ._timeline_data import timeline_chart_data

__all__ = ["ProcessWidget", "events_table_html", "parameter_paths_html"]


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


def parameter_paths_html(process: Any) -> str:
    """Read-only list of the parameters below a process, under their paths."""
    rows = []
    for prefix, owner in parameter_owners(process):
        for name in parameter_names(owner):
            value = value_html(owner, name)
            missing = "<span class='cadetgui-param-missing'>missing</span>"
            shown = value if value is not None else missing
            rows.append(
                f"<tr><td><code>{html.escape(prefix)}.{html.escape(name)}</code></td>"
                f"<td>{shown}</td></tr>"
            )
    if not rows:
        return "<em>The flow sheet has no units yet.</em>"
    return (
        "<table class='cadetgui-table'><thead><tr><th>Path</th><th>Value</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _collapsible(title: str, child: W.Widget) -> W.Accordion:
    accordion = W.Accordion(children=[child])
    accordion.set_title(0, title)
    accordion.selected_index = None
    return accordion


class ProcessWidget:
    """A CADET-Process Process: its cycle time and events, and the parameters it reaches.

    The parameters belong to the unit operations; the process reaches them under paths
    such as `flow_sheet.column.length`, which events and optimization refer to. Given a
    flow sheet, it creates the process `name`; `values` (path: value) are set first.
    """

    def __init__(
        self,
        process: Any,
        name: str = "process",
        values: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if isinstance(process, FlowSheet):
            process = Process(process, name)
        for path, value in (values or {}).items():
            set_by_path(process, path, value)
        self.process = process
        self._listeners: List[Callable[[Any], None]] = []
        self.cycle_time = TextField(
            label="cycle_time", value=format_value(process, "cycle_time"), units=r"\mathrm{s}"
        )
        self._events_table = W.HTML()
        self.chart = EventTimelineChart()
        self._paths = W.HTML()
        self.events = _collapsible("Events", W.VBox([self._events_table, self.chart]))
        self.parameters = _collapsible("Parameters by path", self._paths)
        self.code_view = CodeView(self.code)
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Process · {title}</div>"),
            W.HTML(components_html(process.component_system)),
            self.cycle_time,
            self.events,
            self.parameters,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self.cycle_time.observe(lambda change: self._on_cycle_time(change), names="value")
        self.refresh()

    def refresh(self) -> None:
        """Show the current state, e.g. after events or unit parameters changed in code."""
        self.cycle_time.value = format_value(self.process, "cycle_time")
        n_events = len(self.process.events)
        self.events.set_title(0, f"Events ({n_events})")
        self._events_table.value = events_table_html(self.process)
        self.chart.layout.display = "" if n_events else "none"
        data = timeline_chart_data(self.process, self.process.component_system.names, ())
        if n_events and data is not None:
            self.chart.y_label = data["y_label"]
            self.chart.phases = data["phases"]
            self.chart.markers = data["markers"]
            self.chart.series = data["series"]
        self._paths.value = parameter_paths_html(self.process)
        self.code_view.refresh()

    def _on_cycle_time(self, change: dict) -> None:
        text = change["new"].strip()
        if not text or text == format_value(self.process, "cycle_time"):
            return
        error = assign_literal(self.process, "cycle_time", text)
        self.cycle_time.error = error or ""
        if error:
            return
        self.refresh()
        for fn in list(self._listeners):
            fn(self.process)

    def code(self) -> str:
        """Return the CADET-Process code that creates this process, with its events."""
        lines = [
            "from CADETProcess.processModel import Process",
            "",
            f'process = Process({self.process.flow_sheet.name}, "{self.process.name}")',
        ]
        if math.isfinite(float(self.process.cycle_time)):
            lines.append(f"process.cycle_time = {code_literal(self.process, 'cycle_time')}")
        lines += [
            f'process.add_event("{e.name}", "{e.parameter_path}", '
            f"{_state(e.state)}, {e.time:g})"
            for e in sorted(self.process.events, key=lambda e: e.time)
        ]
        return "\n".join(lines)

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
