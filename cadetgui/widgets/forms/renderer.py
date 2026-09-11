from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

import ipywidgets as W

from ...cadetprocessadapter import FieldSpec, ModelSpec
from .._chrome import style_tag
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


_ELEMENT_FOR_KIND: Dict[str, Callable[[FieldSpec], Element]] = {
    "float": lambda f: FloatField(
        label=f.label or f.name,
        value=_coerced_default(f),
        min=f.min,
        max=f.max,
        units=f.units,
        validate=f.validate,
    ),
    "float_list": lambda f: FloatListField(
        label=f.label or f.name,
        value=_coerced_default(f),
        units=f.units,
        component_names=f.component_names,
        validate=f.validate,
    ),
    "bool": lambda f: BoolField(
        label=f.label or f.name, value=_coerced_default(f), units=f.units, validate=f.validate
    ),
    "text": lambda f: TextField(
        label=f.label or f.name, value=_coerced_default(f), units=f.units, validate=f.validate
    ),
    "choice": lambda f: ChoiceField(
        label=f.label or f.name, options=f.options or (), value=_coerced_default(f)
    ),
}


def element_for_field(f: FieldSpec) -> Element:
    """Build the anywidget Element matching a FieldSpec's kind."""
    factory = _ELEMENT_FOR_KIND.get(f.kind)
    if factory is None:
        raise ValueError(f"No element registered for field kind {f.kind!r}")
    return factory(f)


class FormRenderer:
    """Render a ModelSpec into a form of Elements; auto-commits on every valid change."""

    def __init__(
        self, spec: ModelSpec, *, on_built: Optional[Callable[[Any], None]] = None
    ) -> None:
        self.spec = spec
        self.built: Any = None
        self._on_built = on_built
        self.status = W.HTML("<em>Ready.</em>")

        self._elements: Dict[str, Element] = {f.name: element_for_field(f) for f in spec.fields}
        for element in self._elements.values():
            # Not always "value" itself: ChoiceField's `value` is a plain
            # property over `selected_index` (see Element._value_trait_name),
            # since its true value isn't JSON-serializable.
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
        self._commit()

    def _commit(self) -> None:
        if not self.is_valid:
            self.built = None
            self.status.value = (
                "<span style='color:#b00020'>Fix the highlighted field(s) to continue.</span>"
            )
            return
        try:
            values = self.collect_values()
            if self.spec.build is None:
                raise RuntimeError("Spec has no 'build' function.")
            self.built = self.spec.build(values)
            self.status.value = ""  # nothing to say when things are fine
            if self._on_built is not None:
                self._on_built(self.built)
        except Exception as exc:  # noqa: BLE001
            self.built = None
            self.status.value = f"<span style='color:#b00020'>{exc}</span>"

    def _on_reset(self, _btn: Any) -> None:
        for f in self.spec.fields:
            self._elements[f.name].value = _coerced_default(f)
        self._commit()

    def set_values(self, values: Mapping[str, Any]) -> None:
        """Push a dict of field values into the rendered elements and commit.

        Any field name missing from `values` falls back to its own default.
        """
        for f in self.spec.fields:
            value = values[f.name] if f.name in values else _coerced_default(f)
            self._elements[f.name].value = value
        self._commit()

    def display(self) -> None:
        """Render this form in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
