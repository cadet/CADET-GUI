# =========================================
# File: cadetgui/widgets/base.py
# =========================================
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional
from .elements import FloatListInput, FloatListField

import ipywidgets as W

__all__ = ["ListenerMixin", "BaseWidget"]

LABEL_W = "140px"   

def _style_field(w: W.Widget, *, width: str = "300px", label_width: str = LABEL_W, grow: bool = False) -> W.Widget:
    if hasattr(w, "layout"):
        w.layout.width = "100%" if grow else width
        w.layout.min_width = "0"
        if not grow:
            w.layout.flex = "0 0 auto"
    if hasattr(w, "style"):
        try:
            w.style.description_width = label_width    # <<< fixed label column
        except Exception:
            pass
    return w

class ListenerMixin:
    """Reusable mixin that provides listener registration and notification."""

    def __init__(self) -> None:
        self._listeners: list[Callable[[Any], None]] = []

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a listener callback."""
        self._listeners.append(fn)

    def notify(self, value: Any) -> None:
        """Notify all registered listeners with a new value."""
        for fn in list(self._listeners):
            try:
                fn(value)
            except Exception:
                pass


class BaseWidget(ABC):
    """Base widget container with a header, body, and status bar."""

    def __init__(self, *, title: Optional[str] = None) -> None:
        self.title = title or self.__class__.__name__
        self._status = W.HTML("<em>Ready.</em>")
        self._header = W.HTML(f"<h3 style='margin:0'>{self.title}</h3>")
        self._body = self._build_body()
        self.root = W.VBox([self._header, self._body, self._status])
        self._wire_events()

    @abstractmethod
    def _build_body(self) -> W.Widget:
        ...

    def _wire_events(self) -> None:
        """Connect event handlers (optional override)."""

    def set_status(self, text: str) -> None:
        self._status.value = text

    def set_error(self, exc: Exception | str) -> None:
        msg = str(exc) if isinstance(exc, Exception) else exc
        self._status.value = f"<span style='color:#b00'>{msg}</span>"

    def run_safe(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any | None:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.set_error(exc)
            return None

    @staticmethod
    def make_apply_reset(on_apply: Callable[..., Any], on_reset: Callable[..., Any]) -> W.HBox:
        btn_apply = W.Button(description="Apply", button_style="success")
        btn_reset = W.Button(description="Reset")
        btn_apply.on_click(on_apply)
        btn_reset.on_click(on_reset)
        return W.HBox([btn_apply, btn_reset])

    @staticmethod
    def reset_fields(widgets: Dict[str, W.Widget], specs: list[Any]) -> None:
        for f in specs:
            w = widgets[f.name]
            default = f.default
            try:
                if f.kind == "float":
                    w.value = float(default) if default is not None else 0.0
                elif f.kind == "bool":
                    w.value = bool(default)
                elif f.kind == "float_list":
                    init = ", ".join(map(str, default)) if isinstance(default, (list, tuple)) else str(default or "")
                    w.value = init
                else:
                    w.value = str(default or "")
            except Exception:
                pass

    @staticmethod
    def widget_for_field(f: Any) -> W.Widget:
        label   = getattr(f, "label", None) or getattr(f, "name", "")
        kind    = getattr(f, "kind", "text")
        default = getattr(f, "default", None)

        if kind == "float":
            w = W.BoundedFloatText(
                description=label,
                value=float(default) if default is not None else 0,
                min=0.0, step=1e-6, readout_format=".6g",
            )
            return _style_field(w)

        if kind == "bool":
            w = W.Checkbox(description=label, value=bool(default))
            return _style_field(w, width="auto")

        if kind == "float_list":
            # see aligned list component below
            vals = list(default) if isinstance(default, (list, tuple)) else (
                [float(default)] if default is not None else []
            )
            return FloatListField(description=label, values=vals, label_width=LABEL_W)

        w = W.Text(description=label, value=str(default) if default is not None else "")
        return _style_field(w)


    @staticmethod
    def observe_and_rebuild(widget: W.Widget, names: str, rebuild_fn: Callable[[Any], None]) -> None:
        def _on_change(change: dict) -> None:
            if change.get("name") != names:
                return
            rebuild_fn(change.get("new"))

        widget.observe(_on_change, names=names)

    def display(self) -> None:
        from IPython.display import display as _display

        _display(self.root)


