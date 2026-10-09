from __future__ import annotations

from html import escape
from typing import Any, Callable, Dict, List, Tuple

import ipywidgets as W
from CADETProcess.processModel import Inlet, NoBinding

from ...parameters import describe_parameter
from ..elements import TextField
from ._parameter_values import (
    assign_literal,
    code_literal,
    format_value,
    parameter_names,
)
from ._polynomial_editor import PolynomialEditor

__all__ = ["UnitParametersEditor", "parameter_code"]


def _owners(unit: Any) -> List[Tuple[str, Any]]:
    owners = [(unit.name, unit)]
    binding_model = getattr(unit, "binding_model", None)
    if binding_model is not None and not isinstance(binding_model, NoBinding):
        owners.append((f"{unit.name}.binding_model", binding_model))
    return owners


def parameter_code(unit: Any) -> List[str]:
    """List assignments for the set parameters of `unit` and its binding model."""
    lines = []
    for target, owner in _owners(unit):
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

    Values are assigned to the objects, so CADET-Process validates them. An inlet's
    concentration is a cubic profile, edited by its coefficients with a `PolynomialEditor`.
    """

    def __init__(
        self,
        unit: Any,
        on_change: Callable[[], None],
        *,
        drag_profiles: bool = False,
        flow_rate_profile: bool = False,
    ) -> None:
        self.unit = unit
        self._on_change = on_change
        profiles = ("c", "flow_rate") if flow_rate_profile else ("c",)
        self.fields: Dict[str, TextField] = {}
        self.editors: List[PolynomialEditor] = []
        self._owners: Dict[str, Tuple[Any, str]] = {}
        children: List[W.Widget] = []
        for target, owner in _owners(unit):
            if owner is not unit:
                title = f"Binding model · {type(owner).__name__}"
                children.append(W.HTML(f"<div class='cadetgui-param-group'>{title}</div>"))
            for name in parameter_names(owner):
                if isinstance(owner, Inlet) and name in profiles:
                    indices = range(owner.n_comp) if name == "c" else [None]
                    for index in indices:
                        editor = PolynomialEditor(
                            owner, name, index,
                            on_change=self._changed, draggable=drag_profiles,
                        )
                        self.editors.append(editor)
                        children.append(editor.root)
                    continue
                key = f"{target}.{name}"
                unit_label, _description = describe_parameter(owner, name)
                field = TextField(label=name, value=format_value(owner, name), units=unit_label)
                field.observe(lambda change, key=key: self._on_edit(key, change), names="value")
                self.fields[key] = field
                self._owners[key] = (owner, name)
                children.append(field)
        title = f"{escape(unit.name)} · {type(unit).__name__}"
        heading = W.HTML(f"<div class='cadetgui-section-title'>{title}</div>")
        self.root = W.VBox([heading, *children])

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
        self._on_change()
