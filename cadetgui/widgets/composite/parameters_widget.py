from __future__ import annotations

import ast
import html
from typing import Any, Callable, Dict, List

import ipywidgets as W
import numpy as np
from CADETProcess.dataStructure.parameter import NdPolynomial, Polynomial

from ...parameters import describe_parameter
from .._chrome import style_tag
from .._status import status_html
from ..elements import TextField

__all__ = ["ParametersWidget"]


def _editable_names(obj: Any) -> List[str]:
    required = sorted(getattr(obj, "required_parameters", []))
    others = sorted(
        name for name, value in obj.parameters.items()
        if name not in required and not isinstance(value, dict)
    )
    return required + others


def _plain(value: Any) -> Any:
    return value.tolist() if isinstance(value, np.ndarray) else value


def _format(obj: Any, name: str) -> str:
    value = _plain(getattr(obj, name))
    if value is None:
        return ""
    # Polynomial inputs (e.g. Inlet.c) hold [constant, linear, quadratic, cubic] per entry;
    # show only the constants while the profile is constant.
    if isinstance(getattr(type(obj), name, None), (NdPolynomial, Polynomial)):
        rows = value if value and isinstance(value[0], list) else [value]
        if all(not any(row[1:]) for row in rows):
            constants = [row[0] for row in rows]
            value = constants if isinstance(value[0], list) else constants[0]
    return repr(value)


class ParametersWidget:
    """Show and edit the parameters of one CADET-Process object, e.g. a unit operation.

    Fields show what the object holds (empty if unset) and take Python literals such as
    `0.4` or `[1, 2]`, which are assigned to the object, so CADET-Process validates them.
    """

    def __init__(self, obj: Any) -> None:
        self.obj = obj
        self._listeners: List[Callable[[Any], None]] = []
        self.fields: Dict[str, TextField] = {}
        for name in _editable_names(obj):
            unit, _description = describe_parameter(obj, name)
            field = TextField(label=name, value=_format(obj, name), units=unit)
            field.observe(lambda change, name=name: self._on_edit(name, change), names="value")
            self.fields[name] = field

        title = f"{getattr(obj, 'name', '')} · {type(obj).__name__}"
        self._missing = W.HTML()
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>{html.escape(title)}</div>"),
            *self.fields.values(),
            self._missing,
        ])
        self.root.add_class("cadetgui-panel")
        self._refresh_missing()

    def _on_edit(self, name: str, change: dict) -> None:
        field = self.fields[name]
        text = change["new"].strip()
        if not text or text == _format(self.obj, name):
            return
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            field.error = "Enter a number or a list, e.g. 0.4 or [1, 2]."
            return
        try:
            setattr(self.obj, name, value)
        except (ValueError, TypeError) as exc:
            field.error = str(exc)
            return
        field.error = ""
        field.value = _format(self.obj, name)
        self._refresh_missing()
        for fn in list(self._listeners):
            fn(self.obj)

    def _refresh_missing(self) -> None:
        missing = getattr(self.obj, "missing_parameters", [])
        if missing:
            text = "Missing: " + ", ".join(sorted(missing))
            self._missing.value = status_html("warn", text)
        else:
            self._missing.value = status_html("ok", "All required parameters are set.")

    def refresh(self) -> None:
        """Show the object's current values, e.g. after it was changed in code."""
        for name, field in self.fields.items():
            field.value = _format(self.obj, name)
            field.error = ""
        self._refresh_missing()

    def get_value(self) -> Any:
        """Return the CADET-Process object this widget edits."""
        return self.obj

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(obj)` after every accepted edit."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
