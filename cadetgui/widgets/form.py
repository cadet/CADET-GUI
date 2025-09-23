# =========================================
# File: cadetgui/widgets/form.py
# =========================================
from __future__ import annotations

from typing import Any, Dict, Optional

import ipywidgets as W

from .base import BaseWidget
from ..cadetprocessadapter import ModelSpec

__all__ = ["FormRenderer"]


class FormRenderer(BaseWidget):
    """Render a ModelSpec into a form and build an object on Apply."""

    def __init__(self, spec: ModelSpec, *, title: Optional[str] = None) -> None:
        self._spec = spec
        self._widgets: Dict[str, W.Widget] = {}
        self._btn_apply = W.Button(description="Apply", button_style="success")
        self._btn_reset = W.Button(description="Reset")
        self.built: Any = None
        super().__init__(title=title or spec.title)

    def _build_body(self) -> W.Widget:
        rows: list[W.Widget] = []
        for f in self._spec.fields:
            w = BaseWidget.widget_for_field(f)
            self._widgets[f.name] = w
            rows.append(w)
        actions = W.HBox([self._btn_apply, self._btn_reset])
        return W.VBox(rows + [actions])

    def _wire_events(self) -> None:
        self._btn_apply.on_click(self._on_apply)
        self._btn_reset.on_click(self._on_reset)

    def _collect_values(self) -> Dict[str, Any]:
        vals: Dict[str, Any] = {}
        for f in self._spec.fields:
            raw = getattr(self._widgets[f.name], "value", None)
            value = f.transform(raw) if f.transform else raw
            if f.validate:
                f.validate(value)
            vals[f.name] = value
        return vals

    def _on_apply(self, _btn: W.Button) -> None:
        try:
            vals = self._collect_values()
            if self._spec.build is None:
                raise RuntimeError("Spec has no 'build' function.")
            self.built = self._spec.build(vals)
            self.set_status("<em>Built successfully.</em>")
        except Exception as exc:  # noqa: BLE001
            self.built = None
            self.set_error(exc)

    def _on_reset(self, _btn: W.Button) -> None:
        BaseWidget.reset_fields(self._widgets, self._spec.fields)
        self.set_status("<em>Reset to defaults.</em>")


