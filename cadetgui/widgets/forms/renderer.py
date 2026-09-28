from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

import ipywidgets as W

from ...cadetprocessadapter import FieldSpec, ModelSpec
from .._chrome import style_tag
from .._status import status_html
from ..elements import (
    BoolField,
    ChoiceField,
    Element,
    FloatField,
    FloatListField,
    TextField,
)

__all__ = ["FormRenderer", "element_for_field"]


def _coerced_default(f: FieldSpec) -> Any:
    """Field default, coerced to a type the matching element's `value` trait accepts."""
    if f.kind == "float":
        return float(f.default) if f.default is not None else 0.0
    if f.kind == "float_list":
        return list(f.default) if f.default else [0.0]
    if f.kind == "bool":
        return bool(f.default)
    if f.kind == "choice":
        return f.default
    return str(f.default) if f.default is not None else ""


def element_for_field(f: FieldSpec) -> Element:
    """Build the Element matching a FieldSpec's kind."""
    label = f.label or f.name
    value = _coerced_default(f)
    common: Dict[str, Any] = {"label": label, "units": f.units, "validate": f.validate}
    if f.kind == "float":
        return FloatField(value=value, min=f.min, max=f.max, **common)
    if f.kind == "float_list":
        return FloatListField(value=value, component_names=f.component_names, **common)
    if f.kind == "bool":
        return BoolField(value=value, **common)
    if f.kind == "text":
        return TextField(value=value, **common)
    if f.kind == "choice":
        return ChoiceField(label=label, options=f.options or (), value=value)
    raise ValueError(f"No element registered for field kind {f.kind!r}")


class FormRenderer:
    """Render a ModelSpec into a form of Elements; auto-commits on every valid change."""

    def __init__(
        self,
        spec: ModelSpec,
        *,
        on_built: Optional[Callable[[Any], None]] = None,
        on_invalid: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.spec = spec
        self.built: Any = None
        self._on_built = on_built
        self._on_invalid = on_invalid
        self.status = W.HTML()
        self._suspend_commit = False

        self._elements: Dict[str, Element] = {f.name: element_for_field(f) for f in spec.fields}
        for element in self._elements.values():
            element.observe(self._on_field_changed, names=element._value_trait_name)

        self._btn_reset = W.Button(description="Reset")
        self._btn_reset.on_click(self._on_reset)

        header = W.HTML(f"<div class='cadetgui-panel-title'>{spec.title}</div>")
        rows = [self._elements[f.name] for f in spec.fields]
        self.status.add_class("cadetgui-status")
        self.root = W.VBox([W.HTML(style_tag()), header, *rows, self._btn_reset, self.status])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-section")

        self._commit()

    @property
    def is_valid(self) -> bool:
        """Whether every rendered field currently passes its validator."""
        return all(el.is_valid for el in self._elements.values())

    def _first_error(self) -> str:
        for f in self.spec.fields:
            error = self._elements[f.name].error
            if error:
                return f"{f.label or f.name}: {error}"
        return ""

    def set_disabled(self, disabled: bool) -> None:
        """Grey out (or re-enable) every field and the reset button; values are untouched."""
        for element in self._elements.values():
            element.disabled = disabled
        self._btn_reset.disabled = disabled

    def element(self, name: str) -> Element:
        """Return the Element rendered for one field, keyed by FieldSpec.name."""
        return self._elements[name]

    def collect_values(self) -> Dict[str, Any]:
        """Return the current field values, with each field's `transform` applied."""
        values: Dict[str, Any] = {}
        for f in self.spec.fields:
            raw = self._elements[f.name].value
            values[f.name] = f.transform(raw) if f.transform else raw
        return values

    def _on_field_changed(self, _change: dict) -> None:
        if not self._suspend_commit:
            self._commit()

    def _commit(self) -> None:
        if not self.is_valid:
            self.built = None
            self.status.value = status_html("error", "Fix the highlighted field(s) to continue.")
            if self._on_invalid is not None:
                self._on_invalid(self._first_error())
            return
        try:
            values = self.collect_values()
            if self.spec.build is None:
                raise RuntimeError("Spec has no 'build' function.")
            self.built = self.spec.build(values)
            self.status.value = ""
            if self._on_built is not None:
                self._on_built(self.built)
        except Exception as exc:  # noqa: BLE001
            self.built = None
            self.status.value = status_html("error", str(exc))
            if self._on_invalid is not None:
                self._on_invalid(str(exc))

    def _on_reset(self, _btn: Any) -> None:
        self.set_values({})

    def set_values(self, values: Mapping[str, Any]) -> None:
        """Set the given field values (others reset to their defaults) and commit once."""
        self._suspend_commit = True
        try:
            for f in self.spec.fields:
                default = _coerced_default(f)
                self._elements[f.name].value = values.get(f.name, default)
        finally:
            self._suspend_commit = False
        self._commit()
