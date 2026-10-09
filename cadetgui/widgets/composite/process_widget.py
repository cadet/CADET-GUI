from __future__ import annotations

import html
import math
from typing import Any, Callable, Dict, List, Tuple

import ipywidgets as W
import numpy as np
from CADETProcess.processModel import FlowSheet, Inlet, Process

from ...parameters import describe_parameter
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
)
from ._polynomial_editor import PolynomialEditor
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
    `flow_sheet.column.length`. Parameters that events change are locked. An inlet's
    concentration and flow rate are cubic profiles, edited with a `PolynomialEditor`.
    """

    def __init__(self, process: Any, name: str = "process") -> None:
        if isinstance(process, FlowSheet):
            process = Process(process, name)
        self.process = process
        self._listeners: List[Callable[[Any], None]] = []
        self.fields: Dict[str, TextField] = {}
        self.editors: List[PolynomialEditor] = []
        self._owners: Dict[str, Tuple[Any, str]] = {}
        self._parameters = W.VBox()
        self._events_table = W.HTML()
        self.chart = EventTimelineChart()
        self.code_view = CodeView(self.code)
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Process · {title}</div>"),
            W.HTML(components_html(process.component_system)),
            self._parameters,
            W.HTML("<div class='cadetgui-section-title'>Events</div>"),
            self._events_table,
            self.chart,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self.refresh()

    def refresh(self) -> None:
        """Rebuild from the process, e.g. after units or events were added in code."""
        self.fields = {}
        self.editors = []
        self._owners = {}
        children = [_heading("process")]
        children += self._group(self.process, "", ["cycle_time"])
        for prefix, owner in parameter_owners(self.process):
            children.append(_heading(prefix))
            children += self._group(owner, f"{prefix}.", parameter_names(owner))
        self._parameters.children = children
        self._refresh_events()
        self.code_view.refresh()

    def _group(self, owner: Any, prefix: str, names: List[str]) -> List[W.Widget]:
        locked = set(self.process.event_parameters)
        widgets: List[W.Widget] = []
        locked_here = []
        for name in names:
            path = f"{prefix}{name}"
            if isinstance(owner, Inlet) and name in ("c", "flow_rate") and path not in locked:
                indices = range(owner.n_comp) if name == "c" else [None]
                for index in indices:
                    editor = PolynomialEditor(
                        self.process, owner, name, index, on_change=self._changed
                    )
                    self.editors.append(editor)
                    widgets.append(editor.root)
                continue
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
        self._changed()

    def _changed(self) -> None:
        for path, field in self.fields.items():
            field.value = format_value(*self._owners[path])
        for editor in self.editors:
            editor.refresh()
        self._refresh_events()
        self.code_view.refresh()
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

    def code(self) -> str:
        """Return the CADET-Process code that creates this process and sets its parameters."""
        lines = [
            "from CADETProcess.processModel import Process",
            "",
            f'process = Process({self.process.flow_sheet.name}, "{self.process.name}")',
        ]
        if math.isfinite(float(self.process.cycle_time)):
            lines.append(f"process.cycle_time = {code_literal(self.process, 'cycle_time')}")
        for prefix, owner in parameter_owners(self.process):
            target = prefix.removeprefix("flow_sheet.")
            names = list(getattr(owner, "required_parameters", []))
            names += [n for n in ("c", "flow_rate") if isinstance(owner, Inlet)]
            assigned = [n for n in sorted(names) if getattr(owner, n) is not None]
            if assigned:
                lines.append("")
                lines += [f"{target}.{n} = {code_literal(owner, n)}" for n in assigned]
        if self.process.events:
            lines.append("")
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
