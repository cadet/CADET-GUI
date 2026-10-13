from __future__ import annotations

import html
import keyword
from html import escape
from typing import Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W
from CADETProcess.processModel import (
    Cstr,
    GeneralRateModel,
    Inlet,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    NoBinding,
    Outlet,
    TubularReactor,
)
from CADETProcess.processModel.unitOperation import ChromatographicColumnBase

from ...parameters import describe_parameter
from ...process_model.values import (
    assign_literal,
    code_literal,
    format_value,
    unit_parameter_owners,
)
from ..base import Widget
from ..elements import ChoiceField, TextField
from ..ui.format import unit_html
from ..ui.html import status_html
from ..ui.layout import CodeView, panel
from .profiles import PolynomialEditor
from .sync import changed, watch
from .values import MISSING_HTML, parameter_groups, value_html

__all__ = [
    "UnitOperationsWidget",
    "UNIT_OPERATION_MODELS",
    "UnitParametersEditor",
    "parameter_code",
    "UnitOperationWidget",
    "parameters_html",
]


def parameter_code(unit: Any) -> List[str]:
    """List assignments for the set parameters of `unit` and its binding model."""
    lines = []
    for target, owner in unit_parameter_owners(unit):
        names = list(getattr(owner, "required_parameters", []))
        if isinstance(owner, Inlet):
            names += ["c", "flow_rate"]
        lines += [
            f"{target}.{name} = {code_literal(owner, name)}"
            for name in sorted(names)
            if getattr(owner, name) is not None
        ]
    return lines


class UnitParametersEditor:
    """Edit the parameters of one unit operation, and of its binding model.

    Required parameters come first, and a status line lists those still missing, as
    `required_parameters` and `missing_parameters` do in CADET-Process. Values are
    assigned to the objects, so CADET-Process validates them. An inlet's concentration
    is a cubic profile, edited by its coefficients with a `PolynomialEditor`.
    """

    def __init__(
        self,
        unit: Any,
        on_change: Callable[[], None],
        *,
        flow_rate_profile: bool = False,
    ) -> None:
        self.unit = unit
        self._on_change = on_change
        profiles = ("c", "flow_rate") if flow_rate_profile else ("c",)
        self.fields: Dict[str, TextField] = {}
        self.editors: List[PolynomialEditor] = []
        self._owners: Dict[str, Tuple[Any, str]] = {}
        self._profiles = profiles
        children: List[W.Widget] = []
        for target, owner in unit_parameter_owners(unit):
            if owner is not unit:
                title = f"Binding model · {type(owner).__name__}"
                children.append(W.HTML(f"<div class='cadetgui-section-title'>{title}</div>"))
            for group, group_names in parameter_groups(owner):
                children.append(W.HTML(f"<div class='cadetgui-param-group'>{group}</div>"))
                for name in group_names:
                    children += self._widgets_for(target, owner, name)
        self.status = W.HTML()
        title = f"{escape(unit.name)} · {type(unit).__name__}"
        heading = W.HTML(f"<div class='cadetgui-section-title'>{title}</div>")
        self.root = W.VBox([heading, self.status, *children])
        self._show_missing()

    def _widgets_for(self, target: str, owner: Any, name: str) -> List[W.Widget]:
        if isinstance(owner, Inlet) and name in self._profiles:
            indices = range(owner.n_comp) if name == "c" else [None]
            editors = [
                PolynomialEditor(
                    owner, name, index, on_change=self._changed
                )
                for index in indices
            ]
            self.editors += editors
            return [editor.root for editor in editors]
        key = f"{target}.{name}"
        unit_label, _description = describe_parameter(owner, name)
        field = TextField(
            label=name, value=format_value(owner, name), units=unit_label, compact=True
        )
        field.observe(lambda change, key=key: self._on_edit(key, change), names="value")
        self.fields[key] = field
        self._owners[key] = (owner, name)
        return [field]

    def _show_missing(self) -> None:
        missing = self.unit.missing_parameters
        if missing:
            self.status.value = status_html("warn", "Missing: " + ", ".join(sorted(missing)))
        else:
            self.status.value = status_html("ok", "All required parameters are set.")

    def _on_edit(self, key: str, change: dict) -> None:
        owner, name = self._owners[key]
        field = self.fields[key]
        text = change["new"].strip()
        if not text or text == format_value(owner, name):
            return
        error = assign_literal(owner, name, text)
        field.error = error or ""
        if error:
            return
        self._changed()

    def _changed(self) -> None:
        for key, field in self.fields.items():
            field.value = format_value(*self._owners[key])
        self._show_missing()
        self._on_change()


def _row(obj: Any, name: str, missing: bool) -> str:
    unit, description = describe_parameter(obj, name)
    value = value_html(obj, name)
    if missing or value is None:
        shown = MISSING_HTML if missing else "–"
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
    missing = set(getattr(obj, "missing_parameters", []))
    parts: List[str] = []
    for title, names in parameter_groups(obj):
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
        self.name_field = TextField(label="Name:", value=_suggested_name(Inlet), compact=True)
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
