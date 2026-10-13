from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ...instrument.templates import INSTRUMENT_TEMPLATES, template_required_units
from ..elements import ChoiceField
from ..forms import FormRenderer

__all__ = ["TemplateEditor", "available_templates", "copy_events"]


def available_templates(flow_sheet: Any) -> List[str]:
    """Process templates that `flow_sheet` (an `LCFlowSheet`) has all units for."""
    units = {unit.name for unit in flow_sheet.units}
    return [
        name for name, spec in INSTRUMENT_TEMPLATES.items()
        if template_required_units(spec) <= units
    ]


def copy_events(source: Any, target: Any) -> None:
    """Give `target` the cycle time and events of `source`, at their resolved times and states."""
    for event in list(target.events):
        target.remove_event(event.name)
    target.cycle_time = source.cycle_time
    for event in source.events:
        target.add_event(event.name, event.parameter_path, event.full_state, event.time)


class TemplateEditor:
    """Define the events of a process by a process template of its `LCFlowSheet`.

    Every valid change builds the template and copies its events into the process, so the
    process object stays the same; its raw events are what the template produced.
    """

    def __init__(self, process: Any, on_change: Callable[[], None]) -> None:
        self.process = process
        self._on_change = on_change
        names = available_templates(process.flow_sheet)
        self.picker = ChoiceField(label="template", options=[(name, name) for name in names])
        self.form: Optional[FormRenderer] = None
        self._template_class: Optional[type] = None
        self._form_box = W.VBox()
        self.root = W.VBox([self.picker, self._form_box])
        self.picker.observe(lambda _change: self._show_form(), names="selected_index")
        self._show_form()

    def _show_form(self) -> None:
        self._template_class = None
        spec = INSTRUMENT_TEMPLATES[self.picker.value](self.process.flow_sheet)
        self.form = FormRenderer(spec, on_built=self._on_built)
        self._form_box.children = [self.form.root]

    def _on_built(self, template_process: Any) -> None:
        copy_events(template_process, self.process)
        self._template_class = type(template_process)
        self._on_change()

    def values(self) -> Dict[str, Any]:
        """Return the template's field values, as passed to its class."""
        return self.form.collect_values()

    def code(self) -> Optional[str]:
        """Return the template call that creates this process, or None if it is not built."""
        cls = self._template_class
        if cls is None:
            return None
        flow_sheet = self.process.flow_sheet.name or "flow_sheet"
        lines = [
            f"from CADETProcess.instruments import {cls.__name__}",
            "",
            f'process = {cls.__name__}("{self.process.name}", {flow_sheet},',
        ]
        lines += [f"    {key}={value!r}," for key, value in self.values().items()]
        lines.append(")")
        return "\n".join(lines)
