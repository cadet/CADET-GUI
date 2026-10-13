from __future__ import annotations

import html
import math
from typing import Any, Mapping, Optional

import ipywidgets as W
import numpy as np
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import FlowSheet, Process

from ...process_model.values import (
    assign_literal,
    code_literal,
    format_value,
    parameter_names,
    parameter_owners,
    set_by_path,
)
from ..base import Widget
from ..elements import EventTimelineChart, TextField
from ..instrument.templates import TemplateEditor, available_templates
from ..ui.html import table_html
from ..ui.layout import CodeView, collapsible, panel
from .events import EventEditor
from .sync import changed, watch
from .timeline import show_timeline
from .values import MISSING_HTML, components_html, value_html

__all__ = ["ProcessWidget", "parameter_paths_html"]


def _state(value: Any) -> str:
    return repr(value.tolist() if isinstance(value, np.ndarray) else value)


def parameter_paths_html(process: Any) -> str:
    """Read-only list of the parameters below a process, under their paths."""
    rows = []
    for prefix, owner in parameter_owners(process):
        missing = set(getattr(owner, "missing_parameters", []))
        for name in parameter_names(owner):
            value = value_html(owner, name)
            if name in missing:
                shown = MISSING_HTML
            else:
                shown = "–" if value is None else value
            rows.append([f"<code>{html.escape(prefix)}.{html.escape(name)}</code>", shown])
    return table_html(
        ["Path", "Value"], rows, empty_html="<em>The flow sheet has no units yet.</em>"
    )


class ProcessWidget(Widget):
    """A CADET-Process Process: its cycle time and events, and the parameters it reaches.

    The parameters belong to the unit operations; the process reaches them under paths
    such as `flow_sheet.column.length`, which events and optimization refer to. Given a
    flow sheet, it creates the process `name`; `values` (path: value) are set first.
    Listeners get the process after every accepted edit.
    """

    def __init__(
        self,
        process: Any,
        name: str = "process",
        values: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__()
        if isinstance(process, FlowSheet):
            process = Process(process, name)
        for path, value in (values or {}).items():
            set_by_path(process, path, value)
        self.process = process
        self.cycle_time = TextField(
            label="cycle_time", value=format_value(process, "cycle_time"), units=r"\mathrm{s}",
            compact=True,
        )
        self.chart = EventTimelineChart()
        self.event_editor = EventEditor(process, self._edited)
        self.template_editor: Optional[TemplateEditor] = None
        self._editor_box = W.VBox([self.event_editor.controls])
        has_templates = isinstance(process.flow_sheet, LCFlowSheet) and bool(
            available_templates(process.flow_sheet)
        )
        self.mode = W.ToggleButtons(options=["Raw events", "Template"], value="Raw events")
        self.mode.layout.display = "" if has_templates else "none"
        self.mode.observe(lambda _change: self._on_mode(), names="value")
        self._editor_box.layout = W.Layout(flex="3 1 0", min_width="0")
        self.chart.layout = W.Layout(flex="2 1 0", min_width="0")
        self._editor_and_chart = W.HBox(
            [self._editor_box, self.chart], layout=W.Layout(gap="16px", align_items="flex-start")
        )
        self._paths = W.HTML()
        self._components = W.HTML()
        self.events = collapsible(
            "Events",
            W.VBox([self.mode, self.event_editor.table, self._editor_and_chart]),
        )
        self.parameters = collapsible("Parameters by path", self._paths)
        self.code_view = CodeView(self.code)
        title = html.escape(process.name)
        self.root = panel(
            f"Process · {title}",
            self._components,
            self.cycle_time,
            self.events,
            self.parameters,
            self.code_view.root,
        )
        self.cycle_time.observe(lambda change: self._on_cycle_time(change), names="value")
        watch(process.component_system, self)
        self.refresh()

    def refresh(self) -> None:
        """Show the current state, e.g. after events or unit parameters changed in code."""
        self._components.value = components_html(self.process.component_system)
        self.cycle_time.value = format_value(self.process, "cycle_time")
        n_events = len(self.process.events)
        self.events.set_title(0, f"Events ({n_events})")
        self.chart.layout.display = "" if n_events else "none"
        if n_events:
            show_timeline(self.chart, self.process, self.process.component_system.names)
        self._paths.value = parameter_paths_html(self.process)
        self.event_editor.refresh()
        self.code_view.refresh()

    def _on_cycle_time(self, change: dict) -> None:
        text = change["new"].strip()
        if not text or text == format_value(self.process, "cycle_time"):
            return
        error = assign_literal(self.process, "cycle_time", text)
        self.cycle_time.error = error or ""
        if error:
            return
        self._edited()

    def _on_mode(self) -> None:
        if self.mode.value == "Template":
            if self.template_editor is None:
                self.template_editor = TemplateEditor(self.process, self._edited)
            self._editor_box.children = [self.template_editor.root]
        else:
            self._editor_box.children = [self.event_editor.controls]
        self.code_view.refresh()

    def _edited(self) -> None:
        self.refresh()
        changed(self.process.component_system, self)
        self._notify(self.process)

    def code(self) -> str:
        """Return the CADET-Process code that creates this process: template call or events."""
        if self.mode.value == "Template" and self.template_editor is not None:
            template_code = self.template_editor.code()
            if template_code is not None:
                return template_code
        lines = [
            "from CADETProcess.processModel import Process",
            "",
            f'process = Process({self.process.flow_sheet.name or "flow_sheet"}, '
            f'"{self.process.name}")',
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
