from __future__ import annotations

import html
import keyword
from typing import Any, Dict, List, Optional

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

from ..base import Widget
from ..elements import ChoiceField, TextField
from ..ui.html import status_html
from ..ui.layout import CodeView, panel
from ._model_sync import changed, watch
from ._unit_parameters import UnitParametersEditor, parameter_code

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


class UnitOperationsWidget(Widget):
    """Create unit operations by model and name, and set their parameters.

    Listeners get `units` whenever a unit is created, removed or a parameter changes.

    Created units are stored in `units`, a dict of name: unit operation, which is filled in
    place when given; entries that are model classes are created right away. With
    `edit=False` it only creates units, with `create=False` it only sets parameters, e.g. to
    show both steps separately on one `units` dict. `flow_rate_profile` also edits the
    inlet's flow rate as a profile.
    """

    def __init__(
        self,
        component_system: Any,
        units: Optional[Dict[str, Any]] = None,
        *,
        create: bool = True,
        edit: bool = True,
        flow_rate_profile: bool = False,
    ) -> None:
        super().__init__()
        self.component_system = component_system
        self._editor_options = {"flow_rate_profile": flow_rate_profile}
        self.parameter_picker = ChoiceField(label="Parameters of:", options=[])
        self.editor: Optional[UnitParametersEditor] = None
        self._editor_box = W.VBox()
        self.units: Dict[str, Any] = {} if units is None else units
        self.model_picker = ChoiceField(label="Model:", options=list(UNIT_OPERATION_MODELS.items()))
        self.name_field = TextField(label="Name:", value=_suggested_name(Inlet))
        self.create_button = W.Button(description="Create", icon="plus")
        self.status = W.HTML()
        self._list = W.VBox()
        self.code_view = CodeView(self.code)
        title = "Unit operations" if create and edit else (
            "Create unit operations" if create else "Unit operation parameters"
        )
        children: List[W.Widget] = []
        if create:
            children += [
                self.model_picker, self.name_field, self.create_button, self.status, self._list,
            ]
        if edit:
            children += [self.parameter_picker, self._editor_box]
        self.root = panel(title, *children, self.code_view.root)
        self.model_picker.observe(lambda _change: self._suggest_name(), names="selected_index")
        self.create_button.on_click(lambda _button: self.create())
        self.parameter_picker.observe(lambda _change: self._show_editor(), names="selected_index")
        for name, model in list(self.units.items()):
            if isinstance(model, type):
                self.units[name] = model(component_system, name)
        watch(component_system, self)
        if self.units:
            self.refresh()
            self._suggest_name()

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
        component_system = self.component_system
        if component_system.n_comp == 0:
            self.status.value = status_html("error", "Add a component first.")
            return None
        unit = self.model_picker.value(component_system, name)
        self.units[name] = unit
        self.status.value = ""
        self._changed()
        self.parameter_picker.value = unit
        self._suggest_name()
        return unit

    def remove(self, name: str) -> None:
        """Remove the unit named `name`."""
        del self.units[name]
        self._changed()

    def _changed(self) -> None:
        self.refresh()
        self._edited()

    def refresh(self) -> None:
        """Show the current units and parameters, e.g. after they were changed in code."""
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
        self.parameter_picker.set_options(
            [(name, unit) for name, unit in self.units.items()], keep_value=True
        )
        self.parameter_picker.layout.display = "" if self.units else "none"
        self._show_editor()
        self.code_view.refresh()

    def _show_editor(self) -> None:
        unit = self.parameter_picker.value
        if self.editor is not None and self.editor.unit is unit:
            return
        self.editor = (
            None if unit is None
            else UnitParametersEditor(unit, self._edited, **self._editor_options)
        )
        self._editor_box.children = [] if self.editor is None else [self.editor.root]

    def _edited(self) -> None:
        self.code_view.refresh()
        changed(self.component_system, self)
        self._notify(self.units)

    def code(self) -> str:
        """Return the CADET-Process code that creates these unit operations."""
        classes = sorted({type(unit).__name__ for unit in self.units.values()})
        if not classes:
            return "# No unit operations yet."
        lines = [f"from CADETProcess.processModel import {', '.join(classes)}", ""]
        for name, unit in self.units.items():
            lines.append(f'{name} = {type(unit).__name__}(component_system, "{name}")')
            lines += parameter_code(unit)
        return "\n".join(lines)

    def get_value(self) -> Dict[str, Any]:
        """Return the created unit operations by name."""
        return dict(self.units)
