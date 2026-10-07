from __future__ import annotations

import html
import math
from typing import Optional

import ipywidgets as W

from ..elements import TextField
from ._measurement_common import _ML_PER_MIN
from .configuration import ConfigurationWidget

__all__ = ["FlowRateSection"]


def _check_flow_rate(text: str) -> Optional[str]:
    try:
        value = float(text)
    except ValueError:
        return "Enter the flow rate in mL/min."
    return None if value > 0 and math.isfinite(value) else "Enter a positive flow rate."


class FlowRateSection:
    """A "Flow rate" section (mL/min) that sets `configuration.set_flow_rate`.

    The field follows the configuration's flow rate unless it holds an unsaved edit.
    """

    def __init__(self, configuration: ConfigurationWidget, *, note: str = "") -> None:
        self.configuration = configuration
        self.field = TextField(label="Flow rate:", units="mL/min", validate=_check_flow_rate)
        self._sync()
        self.field.observe(lambda _c: self._on_edit(), names="value")
        configuration.add_listener(lambda *_: self._sync())
        self.root = W.VBox([
            W.HTML("<div class='cadetgui-section-title'>Flow rate</div>"),
            self.field,
            W.HTML(f"<small>{html.escape(note)}</small>" if note else ""),
        ])
        self.root.add_class("cadetgui-section")

    def _sync(self) -> None:
        value = self.configuration.flow_rate
        current = self.field.value.strip()
        try:
            same = value is not None and bool(current) and math.isclose(
                float(current) * _ML_PER_MIN, value, rel_tol=1e-9
            )
        except ValueError:
            return
        if not same:
            self.field.value = f"{value / _ML_PER_MIN:.6g}" if value is not None else ""

    def _on_edit(self) -> None:
        if _check_flow_rate(self.field.value) is not None:
            return
        value = float(self.field.value) * _ML_PER_MIN
        current = self.configuration.flow_rate
        if current is None or not math.isclose(current, value, rel_tol=1e-9):
            self.configuration.set_flow_rate(value)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
