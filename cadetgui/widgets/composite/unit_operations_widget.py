from __future__ import annotations

import html
import keyword
from typing import Any, Callable, Dict, List

import ipywidgets as W
from CADETProcess.processModel import (
    Cstr,
    GeneralRateModel,
    Inlet,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    Outlet,
    TubularReactor,
)

from .._chrome import style_tag
from .._status import status_html
from ..elements import ChoiceField, TextField
from ._code_view import CodeView

__all__ = ["UnitOperationsWidget", "UNIT_OPERATION_MODELS"]

UNIT_OPERATION_MODELS: Dict[str, type] = {
    "Inlet": Inlet,
    "Outlet": Outlet,
    "Lumped Rate Model Without Pores (LRM)": LumpedRateModelWithoutPores,
    "Lumped Rate Model With Pores (LRMP)": LumpedRateModelWithPores,
    "General Rate Model (GRM)": GeneralRateModel,
    "Continuous Stirred Tank Reactor (CSTR)": Cstr,
    "Tubular reactor": TubularReactor,
}

_SUGGESTED_NAMES = {
    Inlet: "inlet", Outlet: "outlet", Cstr: "cstr", TubularReactor: "tubular_reactor",
}


def _suggested_name(model: type) -> str:
    return _SUGGESTED_NAMES.get(model, "column")


class UnitOperationsWidget:
    """Create unit operations by model and name; `units` holds them by name.

    Their parameters are set on the process level, e.g. with the `ProcessWidget`.
    """

    def __init__(self, component_system: Any) -> None:
        self.component_system = component_system
        self.units: Dict[str, Any] = {}
        self._listeners: List[Callable[[Any], None]] = []
        self.model_picker = ChoiceField(label="Model:", options=list(UNIT_OPERATION_MODELS.items()))
        self.name_field = TextField(label="Name:", value=_suggested_name(Inlet))
        self.create_button = W.Button(description="Create", icon="plus")
        self.status = W.HTML()
        self._list = W.VBox()
        self.code_view = CodeView(self.code)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML("<div class='cadetgui-panel-title'>Unit operations</div>"),
            self.model_picker,
            self.name_field,
            self.create_button,
            self.status,
            self._list,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self.model_picker.observe(lambda _change: self._suggest_name(), names="selected_index")
        self.create_button.on_click(lambda _button: self.create())

    def _suggest_name(self) -> None:
        name = _suggested_name(self.model_picker.value)
        candidate, n = name, 2
        while candidate in self.units:
            candidate, n = f"{name}_{n}", n + 1
        self.name_field.value = candidate

    def create(self) -> Any:
        """Create a unit of the selected model under the entered name, and return it."""
        name = self.name_field.value.strip()
        if not name.isidentifier() or keyword.iskeyword(name):
            self.status.value = status_html("error", "Use a name like column or column_2.")
            return None
        if name in self.units:
            self.status.value = status_html("error", f"There is already a unit named {name}.")
            return None
        unit = self.model_picker.value(self.component_system, name)
        self.units[name] = unit
        self.status.value = ""
        self._changed()
        self._suggest_name()
        return unit

    def remove(self, name: str) -> None:
        """Remove the unit named `name`."""
        del self.units[name]
        self._changed()

    def _changed(self) -> None:
        rows = []
        for name, unit in self.units.items():
            button = W.Button(
                description="✕", tooltip=f"Remove {name}", layout=W.Layout(width="36px")
            )
            button.on_click(lambda _button, name=name: self.remove(name))
            label = W.HTML(
                f"<span class='cadetgui-param-label'>{html.escape(name)}</span> "
                f"<code class='cadetgui-param-attr'>{type(unit).__name__}</code>"
            )
            rows.append(W.HBox([button, label]))
        self._list.children = rows
        self.code_view.refresh()
        for fn in list(self._listeners):
            fn(self.units)

    def code(self) -> str:
        """Return the CADET-Process code that creates these unit operations."""
        classes = sorted({type(unit).__name__ for unit in self.units.values()})
        if not classes:
            return "# No unit operations yet."
        lines = [f"from CADETProcess.processModel import {', '.join(classes)}", ""]
        lines += [
            f'{name} = {type(unit).__name__}(component_system, "{name}")'
            for name, unit in self.units.items()
        ]
        return "\n".join(lines)

    def get_value(self) -> Dict[str, Any]:
        """Return the created unit operations by name."""
        return dict(self.units)

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(units)` whenever a unit is created or removed."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
