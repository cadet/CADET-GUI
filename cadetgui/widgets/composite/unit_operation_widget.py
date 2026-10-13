from __future__ import annotations

from html import escape
from typing import Any, List

import ipywidgets as W
from CADETProcess.processModel import NoBinding
from CADETProcess.processModel.unitOperation import ChromatographicColumnBase

from ...parameters import describe_parameter
from ..base import Widget
from ..ui.format import unit_html
from ..ui.layout import panel
from ._parameter_values import parameter_names, value_html

__all__ = ["UnitOperationWidget", "parameters_html"]


def _row(obj: Any, name: str, missing: bool) -> str:
    unit, description = describe_parameter(obj, name)
    value = value_html(obj, name)
    if missing or value is None:
        shown = "<span class='cadetgui-param-missing'>missing</span>" if missing else "–"
    else:
        shown = f"{value} <span class='cadetgui-param-unit'>{unit_html(unit)}</span>"
    note = f"<div class='cadetgui-param-desc'>{escape(description)}</div>" if description else ""
    return (
        "<div class='cadetgui-param'>"
        f"<div><code class='cadetgui-param-label'>{escape(name)}</code>{note}</div>"
        f"<div class='cadetgui-param-value'>{shown}</div>"
        "</div>"
    )


def parameters_html(obj: Any) -> str:
    """Read-only list of the parameters of `obj`: required ones first, then the others."""
    required = set(getattr(obj, "required_parameters", []))
    missing = set(getattr(obj, "missing_parameters", []))
    groups = (
        ("Model parameters", [n for n in parameter_names(obj) if n in required]),
        ("Initial state and options" if required else "Parameters",
         [n for n in parameter_names(obj) if n not in required]),
    )
    parts: List[str] = []
    for title, names in groups:
        if names:
            parts.append(f"<div class='cadetgui-param-group'>{title}</div>")
            parts += [_row(obj, name, name in missing) for name in names]
    if not parts:
        return "<em>No parameters.</em>"
    return f"<div class='cadetgui-params'>{''.join(parts)}</div>"


class UnitOperationWidget(Widget):
    """Read-only view of a unit operation: its model, parameters and binding model."""

    def __init__(self, unit: Any) -> None:
        super().__init__()
        self.unit = unit
        self._body = W.HTML()
        self.root = panel(None, self._body)
        self.refresh()

    def refresh(self) -> None:
        """Show the unit's current values, e.g. after they were changed in code."""
        title = f"{escape(self.unit.name)} · {type(self.unit).__name__}"
        parts = [f"<div class='cadetgui-panel-title'>{title}</div>", parameters_html(self.unit)]
        if isinstance(self.unit, ChromatographicColumnBase):
            binding_model = self.unit.binding_model
            if isinstance(binding_model, NoBinding):
                parts.append("<div class='cadetgui-param-group'>Binding model: none</div>")
            else:
                parts.append(
                    "<div class='cadetgui-param-group'>Binding model: "
                    f"{type(binding_model).__name__}</div>"
                )
                parts.append(parameters_html(binding_model))
        self._body.value = "".join(parts)

    def get_value(self) -> Any:
        """Return the unit operation this widget shows."""
        return self.unit
