from __future__ import annotations

from html import escape
from typing import Any

import ipywidgets as W
from CADETProcess.processModel import NoBinding

from ...parameters import describe_parameter
from .._chrome import style_tag
from .._units import unit_html
from ._parameter_values import format_value, parameter_names

__all__ = ["UnitOperationWidget", "parameter_table_html"]


def parameter_table_html(obj: Any) -> str:
    """Read-only table of the parameters of `obj`: value, unit and description."""
    required = set(getattr(obj, "required_parameters", []))
    missing = set(getattr(obj, "missing_parameters", []))
    rows = []
    for name in parameter_names(obj):
        unit, description = describe_parameter(obj, name)
        value = format_value(obj, name)
        if name in missing:
            value = "<span class='cadetgui-msg cadetgui-msg-warn'>missing</span>"
        else:
            value = f"<code>{escape(value)}</code>"
        label = f"<code>{escape(name)}</code>{' *' if name in required else ''}"
        rows.append(
            f"<tr><td>{label}</td><td>{value}</td><td>{unit_html(unit)}</td>"
            f"<td>{escape(description)}</td></tr>"
        )
    if not rows:
        return "<em>No parameters.</em>"
    return (
        "<table class='cadetgui-table'><thead><tr><th>Parameter</th><th>Value</th>"
        f"<th>Unit</th><th>Description</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        "<small>* required</small>"
    )


class UnitOperationWidget:
    """Read-only view of a unit operation: its model, parameters and binding model."""

    def __init__(self, unit: Any) -> None:
        self.unit = unit
        self._body = W.HTML()
        self.root = W.VBox([W.HTML(style_tag()), self._body])
        self.root.add_class("cadetgui-panel")
        self.refresh()

    def refresh(self) -> None:
        """Show the unit's current values, e.g. after they were changed in code."""
        title = f"{escape(self.unit.name)} · {type(self.unit).__name__}"
        parts = [
            f"<div class='cadetgui-panel-title'>{title}</div>",
            parameter_table_html(self.unit),
        ]
        binding_model = getattr(self.unit, "binding_model", None)
        if binding_model is not None:
            parts.append(
                "<div class='cadetgui-section-title'>Binding model · "
                f"{type(binding_model).__name__}</div>"
            )
            if not isinstance(binding_model, NoBinding):
                parts.append(parameter_table_html(binding_model))
        self._body.value = "".join(parts)

    def get_value(self) -> Any:
        """Return the unit operation this widget shows."""
        return self.unit

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
