# =========================================
# File: cadetgui/widgets/elements.py
# =========================================
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple, TypeVar

import ipywidgets as W

__all__ = [
    "Element",
    "TextField",
    "FloatField",
    "BoolField",
    "Display",
    "ChoiceField",
    "ObjectChoiceField",
    "Modal",
]

T = TypeVar("T")


class Element(ABC):
    """Base class for small reusable form elements."""

    widget: W.Widget

    @abstractmethod
    def get_value(self) -> Any:
        """Return the current value."""

    @abstractmethod
    def set_value(self, value: Any) -> None:
        """Set the current value."""


class TextField(Element):
    """Single-line text input with label."""

    def __init__(self, *, label: str = "", value: str = "") -> None:
        self.widget = W.Text(description=label, value=value)

    def get_value(self) -> str:  # type: ignore[override]
        return str(self.widget.value)

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        self.widget.value = str(value)


class FloatField(Element):
    """Float input with label."""

    def __init__(self, *, label: str = "", value: float = 0.0) -> None:
        self.widget = W.FloatText(description=label, value=float(value))

    def get_value(self) -> float:  # type: ignore[override]
        return float(self.widget.value)

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        self.widget.value = float(value)


class BoolField(Element):
    """Boolean checkbox with label."""

    def __init__(self, *, label: str = "", value: bool = False) -> None:
        self.widget = W.Checkbox(description=label, value=bool(value))

    def get_value(self) -> bool:  # type: ignore[override]
        return bool(self.widget.value)

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        self.widget.value = bool(value)


class Display(Element):
    """Read-only HTML display block."""

    def __init__(self, *, html: str = "") -> None:
        self.widget = W.HTML(value=html)

    def get_value(self) -> str:  # type: ignore[override]
        return str(getattr(self.widget, "value", ""))

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        self.widget.value = str(value)

class FloatListInput(W.VBox):
    """Editable list of positive floats with +/− controls (no textarea)."""

    def __init__(self, *, label: str = "", values: list[float] | None = None,
                 min_val: float = 1e-300, step: float = 1e-6) -> None:
        self._min = min_val
        self._step = step
        self._rows = W.VBox([])
        self._add = W.Button(icon="plus", tooltip="Add value")
        self._label = W.Label(label) if label else W.Label()
        super().__init__([self._label, self._rows, self._add],
                         layout=W.Layout(width="100%", min_width="0"))

        for v in (values if values else [0.0]):
            self._add_row(float(v) if v is not None else 0.0)

        self._add.on_click(lambda _: self._add_row())

    def _add_row(self, value: float = 0.0) -> None:
        num = W.BoundedFloatText(
            value=max(value, self._min),
            min=self._min,
            step=self._step,
            readout_format=".6g",
            layout=W.Layout(width="180px", min_width="0", flex="0 0 auto"),
        )
        rm = W.Button(icon="trash", tooltip="Remove")
        row = W.HBox([num, rm], layout=W.Layout(align_items="center"))
        rm.on_click(lambda _b: self._remove_row(row))
        self._rows.children = tuple(list(self._rows.children) + [row])

    def _remove_row(self, row: W.HBox) -> None:
        items = list(self._rows.children)
        try:
            items.remove(row)
            self._rows.children = tuple(items if items else [])
        except ValueError:
            pass

    @property
    def value(self) -> list[float]:
        return [float(ch.children[0].value) for ch in self._rows.children]
    
import ipywidgets as W

class FloatListField(W.HBox):
    """List of positive floats aligned with other fields' description column."""
    def __init__(self, *, description: str, values: list[float] | None = None,
                 label_width: str = "140px", min_val: float = 1e-300, step: float = 1e-6):
        self._min = min_val
        self._step = step
        self._rows = W.VBox([])
        self._add  = W.Button(icon="plus", tooltip="Add value")
        label = W.Label(description, layout=W.Layout(width=label_width, flex="0 0 auto"))

        box = W.VBox([self._rows, self._add], layout=W.Layout(width="100%", min_width="0"))
        super().__init__([label, box],
                         layout=W.Layout(align_items="flex-start", width="100%", min_width="0"))

        for v in (values if values else [min_val]):
            self._add_row(float(v))

        self._add.on_click(lambda _: self._add_row())

    def _add_row(self, value: float) -> None:
        num = W.BoundedFloatText(
            value=max(value, self._min),
            min=self._min, step=self._step, readout_format=".6g",
            layout=W.Layout(width="180px", min_width="0", flex="0 0 auto"),
        )
        rm = W.Button(icon="trash", tooltip="Remove")
        row = W.HBox([num, rm], layout=W.Layout(align_items="center"))
        rm.on_click(lambda _b: self._remove_row(row))
        self._rows.children = tuple(list(self._rows.children) + [row])

    def _remove_row(self, row: W.HBox) -> None:
        items = list(self._rows.children)
        if row in items:
            items.remove(row)
            self._rows.children = tuple(items)

    @property
    def value(self) -> list[float]:
        return [float(ch.children[0].value) for ch in self._rows.children]


class Popup(Element):
    """Light-weight pseudo-modal popup using an Accordion."""

    def __init__(self, *, title: str = "Info", content: Optional[W.Widget] = None) -> None:
        body = content or W.HTML("<em>Empty</em>")
        acc = W.Accordion(children=[body])
        acc.set_title(0, title)
        acc.selected_index = None
        self.widget = acc

    def get_value(self) -> None:  # type: ignore[override]
        return None

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        pass

    def open(self) -> None:
        self.widget.selected_index = 0  # type: ignore[attr-defined]

    def close(self) -> None:
        self.widget.selected_index = None  # type: ignore[attr-defined]

class ChoiceField(Element):
    """Dropdown for selecting one option from (label, value) pairs.

    Parameters
    ----------
    label : str
        Text shown left of the dropdown (ipywidgets 'description').
    options : Sequence[Tuple[str, Any]]
        Iterable of (label, value) pairs.
    value : Any | None
        Initially selected value. If None, uses the first option (if any).
    layout : W.Layout | None
        Optional ipywidgets layout (width, margin, etc.).
    style : dict | None
        Optional widget.style overrides, e.g. {"description_width": "90px"}.
    disabled : bool
        Disable user interaction.
    placeholder : str | None
        If given and value is None, inserts a non-selectable placeholder label.
    class_name : str | None
        CSS class to add to the widget (ipywidgets v8: .add_class; v7: ._dom_classes).
    """

    def __init__(
        self,
        *,
        label: str = "",
        options: Sequence[Tuple[str, Any]] = (),
        value: Any | None = None,
        layout: Optional[W.Layout] = None,
        style: Optional[dict] = None,
        disabled: bool = False,
        placeholder: str | None = None,
        class_name: str | None = None,
    ) -> None:
        # Build options (optionally add a placeholder)
        self._placeholder = None
        if placeholder is not None and (value is None) and len(options) > 0:
            # ipywidgets Dropdown doesn't support a true non-selectable option,
            # so we insert a unique sentinel value and treat it specially.
            self._placeholder = object()
            options = [(placeholder, self._placeholder)] + list(options)

        self.widget = W.Dropdown(description=label, options=list(options), disabled=disabled)

        if layout is not None:
            self.widget.layout = layout
        if style and hasattr(self.widget, "style"):
            for k, v in style.items():
                setattr(self.widget.style, k, v)

        if class_name:
            # v8
            if hasattr(self.widget, "add_class"):
                self.widget.add_class(class_name)
            # v7 fallback
            elif hasattr(self.widget, "_dom_classes"):
                self.widget._dom_classes.add(class_name)

        # Set initial value
        try:
            if value is not None:
                self.widget.value = value
            else:
                # If placeholder present, select it; else leave default (first option)
                if self._placeholder is not None:
                    self.widget.value = self._placeholder
        except Exception:
            pass

    # ---- Element API ----
    def get_value(self) -> Any:  # type: ignore[override]
        v = getattr(self.widget, "value", None)
        # If placeholder is selected, behave as though no value is chosen
        if self._placeholder is not None and v is self._placeholder:
            return None
        return v

    def set_value(self, value: Any) -> None:  # type: ignore[override]
        # Allow setting to None -> move to placeholder (if configured)
        if value is None and self._placeholder is not None:
            self.widget.value = self._placeholder
        else:
            self.widget.value = value

    # ---- Convenience helpers ----
    def set_options(self, options: Sequence[Tuple[str, Any]], *, keep_value: bool = True) -> None:
        """Replace the options. If keep_value=True, try to keep current value if still present."""
        current = self.widget.value
        self.widget.options = list(options)
        if keep_value and any(v == current for _, v in self.widget.options):
            try:
                self.widget.value = current
            except Exception:
                pass
        elif self.widget.options:
            # default to first option
            try:
                self.widget.value = self.widget.options[0][1]
            except Exception:
                pass

    def add_class(self, name: str) -> None:
        if hasattr(self.widget, "add_class"):
            self.widget.add_class(name)  # v8
        elif hasattr(self.widget, "_dom_classes"):
            self.widget._dom_classes.add(name)  # v7

    def disable(self) -> None:
        self.widget.disabled = True

    def enable(self) -> None:
        self.widget.disabled = False

class ObjectChoiceField(ChoiceField):
    """Dropdown for arbitrary objects with a label function (or attribute).

    Parameters
    ----------
    label : str
        Text shown left of the dropdown.
    items : list[object] | dict[str, object]
        Either a list of objects or a mapping of display label -> object.
    label_fn : Callable[[object], str] | None
        Function to produce a label for each object (used when items is a list).
    fallback_attr : str
        Attribute name to read for labels if label_fn is not provided (default: 'name').
    value, layout, style, disabled, placeholder, class_name
        Passed through to ChoiceField.
    """

    def __init__(
        self,
        *,
        label: str = "Select:",
        items: list[object] | dict[str, object],
        label_fn: Optional[Callable[[object], str]] = None,
        fallback_attr: str = "name",
        value: Any | None = None,
        layout: Optional[W.Layout] = None,
        style: Optional[dict] = None,
        disabled: bool = False,
        placeholder: str | None = None,
        class_name: str | None = None,
    ) -> None:
        if isinstance(items, dict):
            pairs = [(str(k), v) for k, v in items.items()]
        else:
            pairs = []
            for obj in items:
                if label_fn is not None:
                    lbl = label_fn(obj)
                else:
                    lbl = getattr(obj, fallback_attr, obj.__class__.__name__)
                pairs.append((str(lbl), obj))

        super().__init__(
            label=label,
            options=pairs,
            value=value,
            layout=layout,
            style=style,
            disabled=disabled,
            placeholder=placeholder,
            class_name=class_name,
        )
        
class Modal:
    def __init__(self, title: str = "Dialog") -> None:
        self._title = title
        self._on_close: list[Callable[[], None]] = []
        self.is_open = False

        self._overlay = W.Box(
            [],
            layout=W.Layout(
                display="none",
                position="absolute",            # ⬅ anchor to root stack
                top="0", left="0", right="0", bottom="0",
                width="100%", height="100%",
                justify_content="center",
                align_items="flex-start",
                background_color="rgba(0,0,0,0.35)",
                z_index="10030",               # ⬅ top of our stack
                pointer_events="auto",
            ),
        )


        # The card/panel (above the backdrop)
        self._title_html = W.HTML()
        self._close_btn = W.Button(description="Close", icon="x")
        self._close_btn.on_click(lambda _: self.close())

        header = W.HBox(
            [self._title_html, self._close_btn],
            layout=W.Layout(justify_content="space-between", align_items="center", width="100%"),
        )

        self.body = W.Box([], layout=W.Layout(flex="1 1 auto", overflow_y="auto", width="100%"))

        self._panel = W.VBox(
            [header, self.body],
            layout=W.Layout(
                width="min(720px, 90vw)",
                max_height="80vh",
                overflow="hidden",
                padding="16px",
                border="1px solid #ccc",
                border_radius="12px",
                background_color="#fff",
                box_shadow="0 8px 24px rgba(0,0,0,0.25)",
                # Critical bits:
                position="relative",            # panel has its own stacking context
                z_index="2147483647",           # above the backdrop (and everything else)
                margin="12px 0 0 0",            # near the top (adjust to taste)
                pointer_events="auto",          # panel captures clicks
            ),
        )

        self._overlay.children = [self._panel]
        self.widget = self._overlay
        self.set_title(title)

    def set_title(self, title: str) -> None:
        self._title = title
        self._title_html.value = f"<h4 style='margin:0'>{title}</h4>"

    def set_body(self, content: W.Widget) -> None:
        self.body.children = [content]

    def open(self, content: W.Widget, *, title: Optional[str] = None) -> None:
        if title:
            self.set_title(title)
        self.set_body(content)
        self._overlay.layout.display = "flex"  # ipywidgets Boxes render with 'flex'
        self.is_open = True

    def close(self) -> None:
        self._overlay.layout.display = "none"
        self.body.children = []
        self.is_open = False
        for fn in list(self._on_close):
            try: fn()
            except Exception: pass
        self._on_close.clear()

    def add_close_listener(self, fn: Callable[[], None]) -> None:
        self._on_close.append(fn)