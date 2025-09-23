from __future__ import annotations

from typing import Any, Callable, Optional, Union, Dict
from threading import Timer
import warnings
import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from .base import BaseWidget, ListenerMixin
from .elements import ChoiceField, ObjectChoiceField, Modal
from .form import FormRenderer
from ..cadetprocessadapter import (
    DEFAULT_COLUMN_FACTORIES,
    MODEL_REGISTRY,
    build_column_config_spec,
)

__all__ = ["ConfigurationWidget"]

# ----------------------
# CSS-like layout tokens
# ----------------------

CSS_ROOT = W.Layout(
    position="relative",
    width="100%",
    overflow="visible",
    display="block",
    z_index="0",
)

CSS_TOOLBAR_WRAP = W.Layout(
    position="relative",
    width="100%",
    overflow="visible",
    z_index="0",
)

# Model & Column pickers row
CSS_TOOLBAR_ROW = W.Layout(
    align_items="center",
    position="relative",
    flex_wrap="wrap",
    min_width="0",
)

# Toolbar popover panel
CSS_TOOLBAR_POPOVER = W.Layout(
    display="none",
    position="absolute",
    top="calc(100% + 8px)",
    right="0",
    width="420px",
    max_height="60vh",
    overflow_y="auto",
    padding="16px",
    border="1px solid #ccc",
    border_radius="12px",
    background_color="#fff",
    box_shadow="0 8px 24px rgba(0,0,0,0.25)",
    z_index="10020",
)

# Main model configuration panel (no horizontal scroll)
CSS_MODEL_PANEL = W.Layout(
    min_height="500px",
    max_width="400px",
    display="block",
    overflow_x="hidden",
)

# Grey overlay dimmer for popovers & modal
CSS_OVERLAY_DIMMER = W.Layout(
    display="none",
    position="absolute",
    top="0", left="0", right="0", bottom="0",
    background_color="rgba(0,0,0,0.25)",
    z_index="10010",
    pointer_events="auto",
)

# Raise a control above overlays if needed
CSS_RAISE_ABOVE_OVERLAY = dict(position="relative", z_index="10040", pointer_events="auto")


# ----------------------
# Utilities
# ----------------------

def _set_attr_path(obj: Any, path: str, value: Any) -> None:
    """Set attribute or mapping by dotted path. Supports 'param:Family.key'."""
    if path.startswith("param:"):
        _, rest = path.split("param:", 1)
        family, key = rest.split(".", 1)
        try:
            obj.parameter[family][key] = value
            return
        except Exception:
            pass
    target = obj
    parts = path.split(".")
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


# ----------------------
# Widget
# ----------------------

class ConfigurationWidget(BaseWidget, ListenerMixin):
    """Unified configuration widget for model/column-based process building.

    - Model Configuration: main panel under the toolbar (builds the process)
    - Column Configuration: modal dialog for editing column parameters
    """

    # ----- init & state -----
    def __init__(
        self,
        *,
        title: Optional[str] = None,
        registry: Optional[dict[str, Callable[[Any], Any]]] = None,
        columns: Optional[Union[list[Any], dict[str, Any]]] = None,
        on_built: Optional[Callable[[Any], None]] = None,
        spec_builder: Optional[type[FormRenderer]] = None,
    ) -> None:
        ListenerMixin.__init__(self)

        use_defaults = registry is None or columns is None or spec_builder is None
        if use_defaults:
            self._DEFAULT_COLUMN_FACTORIES = DEFAULT_COLUMN_FACTORIES
            self._can_rebuild_columns = True
            self._components_value = 1
            columns = DEFAULT_COLUMN_FACTORIES
            registry = MODEL_REGISTRY
            spec_builder = FormRenderer
        else:
            self._DEFAULT_COLUMN_FACTORIES = None
            self._can_rebuild_columns = False
            self._components_value = None

        # External deps / factories
        self._registry = registry
        self._columns = columns
        self._SpecDriven = spec_builder
        self._on_built = on_built

        # Column Config modal
        self._column_modal = Modal("Column configuration")

        # State
        self._built: Any | None = None
        self._column_cache: dict[object, Any] = {}

        # Anti-flicker / concurrency guards
        self._suspend_main_rebuild: bool = False
        self._toolbar_popover_timer: Optional[Timer] = None
        self._toolbar_popover_last_factory: Any = None

        # Detachable observers
        self._obs_model_spec = None
        self._obs_column_spec = None

        # Controls
        self._btn_apply = W.Button(description="Apply", button_style="success")
        self._btn_reset = W.Button(description="Reset")
        self._btn_open_column_modal = W.Button(description="Configure column…", icon="wrench")

        self._components_field: Optional[W.IntText] = (
            W.IntText(description="Components:", value=self._components_value, min=1)
            if self._can_rebuild_columns
            else None
        )

        super().__init__(title=title or "Configuration")

    # Public API
    @property
    def process(self) -> Any | None:
        return self._built

    # ----- UI builders -----
    def _build_toolbar_row(self) -> W.Widget:
        self._model_picker = ObjectChoiceField(label="Model:", items=self._registry)  # type: ignore[arg-type]
        self._column_picker = ChoiceField(label="Column:", options=self._column_pairs)
        for k, v in CSS_RAISE_ABOVE_OVERLAY.items():
            setattr(self._column_picker.widget.layout, k, v)

        row = W.HBox(
            [self._components_field, self._model_picker.widget, self._column_picker.widget, self._btn_open_column_modal],
            layout=CSS_TOOLBAR_ROW,
        )
        return row

    def _build_toolbar_popover(self) -> W.Widget:
        self._toolbar_popover = W.VBox([], layout=CSS_TOOLBAR_POPOVER)
        return self._toolbar_popover

    def _build_model_panel(self) -> W.Widget:
        self._model_panel = W.Box([], layout=CSS_MODEL_PANEL)
        return self._model_panel

    def _build_overlay_dimmer(self) -> W.Widget:
        self._overlay_dimmer = W.Box([], layout=CSS_OVERLAY_DIMMER)
        return self._overlay_dimmer

    # ----- BaseWidget hooks -----
    def _build_body(self) -> W.Widget:
        self._manual_mode = not (self._registry and self._columns)
        if self._manual_mode:
            self._form_box = W.VBox([])
            self._actions = W.HBox([self._btn_apply, self._btn_reset])
            return W.VBox([self._form_box, self._actions])

        # Normalize columns
        if isinstance(self._columns, dict):
            self._column_pairs = list(self._columns.items())
        else:
            self._column_pairs = [
                (getattr(c, "name", c.__class__.__name__), c) for c in self._columns
            ]

        # Toolbar (row + popover anchored to it)
        toolbar_row = self._build_toolbar_row()
        self._toolbar_wrap = W.Box([toolbar_row], layout=CSS_TOOLBAR_WRAP)
        self._toolbar_popover = self._build_toolbar_popover()
        self._toolbar_wrap.children = [toolbar_row, self._toolbar_popover]

        # Model Config panel
        self._model_panel = self._build_model_panel()

        # Content
        self._content = W.VBox([self._toolbar_wrap, self._model_panel], layout=W.Layout(width="100%"))

        # Overlays: dimmer then column modal, all inside the root
        self._overlay_dimmer = self._build_overlay_dimmer()
        self._root = W.Box([self._content, self._overlay_dimmer, self._column_modal.widget], layout=CSS_ROOT)

        return W.VBox([self._root])

    def _wire_events(self) -> None:
        if getattr(self, "_manual_mode", False):
            self._btn_apply.on_click(self._on_apply)
            self._btn_reset.on_click(self._on_reset)
            return

        self._attach_main_observers()
        self._btn_open_column_modal.on_click(self._open_column_modal)

        # Initialize picks
        try:
            mopts = list(self._model_picker.widget.options)
            if mopts:
                self._model_picker.set_value(mopts[0][1])
            copts = list(self._column_picker.widget.options)
            if copts:
                self._column_picker.set_value(copts[0][1])
        except Exception:
            pass

        # Initial form
        model_fn, column = self._get_selection()
        if model_fn and column:
            self._rebuild_model_panel(model_fn, column)

        # Components watcher
        if self._components_field:
            self._components_field.observe(self._on_components_change, names="value")

    # ----- Toolbar popover helpers -----
    def _show_toolbar_popover(self, content: W.Widget, *, title: str | None = None) -> None:
        if getattr(self._column_modal, "is_open", False):
            try:
                self._column_modal.close()
            except Exception:
                pass
        if title:
            title_html = W.HTML(f"<h4 style='margin:0 0 8px 0'>{title}</h4>")
            self._toolbar_popover.children = [title_html, content]
        else:
            self._toolbar_popover.children = [content]
        self._toolbar_popover.layout.display = "flex"
        self._overlay_dimmer.layout.display = "flex"

    def _hide_toolbar_popover(self) -> None:
        self._toolbar_popover.layout.display = "none"
        self._toolbar_popover.children = []
        self._overlay_dimmer.layout.display = "none"

    def _open_toolbar_popover_with_live_update(
        self,
        *,
        initial_factory: Any,
        rebuild_fn: Callable[[Any], FormRenderer],
        title_fn: Callable[[Any], str],
        observe_widget: W.Widget,
        names: str = "value",
    ) -> None:
        if getattr(self._column_modal, "is_open", False):
            try:
                self._column_modal.close()
            except Exception:
                pass

        self._detach_main_observers()
        self._suspend_main_rebuild = True

        def _restore():
            self._suspend_main_rebuild = False
            try:
                observe_widget.unobserve(_on_change, names=names)
            except Exception:
                pass
            if self._toolbar_popover_timer and self._toolbar_popover_timer.is_alive():
                try:
                    self._toolbar_popover_timer.cancel()
                except Exception:
                    pass
            self._attach_main_observers()
            self._hide_toolbar_popover()

        form = rebuild_fn(initial_factory)
        self._toolbar_popover_last_factory = initial_factory
        self._show_toolbar_popover(form.root, title=title_fn(initial_factory))

        self._toolbar_popover_timer = None

        def _do_rebuild(factory: Any) -> None:
            try:
                new_form = rebuild_fn(factory)
                self._toolbar_popover_last_factory = factory
                self._show_toolbar_popover(new_form.root, title=title_fn(factory))
            except Exception as exc:
                self._show_toolbar_popover(W.HTML(f"<span style='color:#b00'>Error: {exc}</span>"))

        def _on_change(change: dict) -> None:
            if change.get("name") != names:
                return
            factory = change.get("new")
            if factory is self._toolbar_popover_last_factory:
                return
            if self._toolbar_popover_timer and self._toolbar_popover_timer.is_alive():
                try:
                    self._toolbar_popover_timer.cancel()
                except Exception:
                    pass
            self._toolbar_popover_timer = Timer(0.12, _do_rebuild, args=(factory,))
            self._toolbar_popover_timer.start()

        observe_widget.observe(_on_change, names=names)
        self._popover_close = _restore  # retained attribute name for backward-compat

    # ----- Build helpers (Model/Column) -----
    def _build_model_form(self, model_fn: Callable[[Any], Any], column: Any) -> FormRenderer:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            spec = model_fn(column)

        form = (self._SpecDriven or FormRenderer)(spec)  # type: ignore[call-arg]

        def _after_apply(_b: W.Button) -> None:
            if getattr(form, "built", None) is not None:
                self._built = form.built
                if self._on_built:
                    self._on_built(form.built)
                self.notify(self._built)

        form._btn_apply.on_click(_after_apply)  # noqa: SLF001
        return form

    def _build_column_form(self, column: Any) -> FormRenderer:
        spec = build_column_config_spec(column)
        form = FormRenderer(spec)

        spec_apply = getattr(spec, "apply", None)

        def _apply_into_column(_b: W.Button) -> None:
            vals: Dict[str, Any] = {}
            for f in spec.fields:
                raw = getattr(form._widgets[f.name], "value", None)  # noqa: SLF001
                val = f.transform(raw) if f.transform else raw
                if f.validate:
                    f.validate(val)
                vals[f.name] = val

            if callable(spec_apply):
                spec_apply(column, vals)
            else:
                targets = getattr(spec, "targets", None) or {}
                wrote_any = False
                for fname, v in vals.items():
                    target_path = targets.get(fname)
                    try:
                        if target_path:
                            _set_attr_path(column, target_path, v)
                            wrote_any = True
                        elif hasattr(column, fname):
                            setattr(column, fname, v)
                            wrote_any = True
                    except Exception:
                        pass
                if not wrote_any:
                    for k, v in vals.items():
                        try:
                            column.parameter["LRMP"][k] = v
                            wrote_any = True
                        except Exception:
                            pass

            name = getattr(column, "name", column.__class__.__name__)
            self.set_status(f"<em>Updated column parameters for: {name}</em>")
            self._hide_toolbar_popover()

        form._btn_apply.on_click(_apply_into_column)  # noqa: SLF001
        return form

    # ----- Selection helpers -----
    def _make_column(self, factory: Callable[[ComponentSystem], Any]) -> Any:
        if factory in self._column_cache:
            return self._column_cache[factory]
        cs = ComponentSystem(self._components_field.value if self._components_field else 1)
        return factory(cs)

    def _get_selection(self) -> tuple[Callable[[Any], Any] | None, Any | None]:
        model_fn = self._model_picker.get_value() if hasattr(self, "_model_picker") else None
        col_factory = self._column_picker.get_value() if hasattr(self, "_column_picker") else None
        column = self._column_cache.get(col_factory) if callable(col_factory) else col_factory
        if column is None and callable(col_factory):
            column = self._make_column(col_factory)
        return model_fn, column

    # ----- Observers attach/detach -----
    def _attach_main_observers(self) -> None:
        if self._obs_model_spec is None:
            self._obs_model_spec = lambda ch: self._on_spec_change(ch)
            self._model_picker.widget.observe(self._obs_model_spec, names="value")
        if self._obs_column_spec is None:
            self._obs_column_spec = lambda ch: self._on_spec_change(ch)
            self._column_picker.widget.observe(self._obs_column_spec, names="value")

    def _detach_main_observers(self) -> None:
        if self._obs_model_spec is not None:
            try:
                self._model_picker.widget.unobserve(self._obs_model_spec, names="value")
            except Exception:
                pass
            self._obs_model_spec = None
        if self._obs_column_spec is not None:
            try:
                self._column_picker.widget.unobserve(self._obs_column_spec, names="value")
            except Exception:
                pass
            self._obs_column_spec = None

    # ----- Event handlers -----
    def _rebuild_model_panel(self, model_fn: Callable[[Any], Any], column: Any) -> None:
        form = self._build_model_form(model_fn, column)
        with self._model_panel.hold_trait_notifications():
            self._model_panel.children = [form.root]
        self.set_status("<em>Select model & column, configure, then click Apply.</em>")

    def _on_spec_change(self, _change: dict) -> None:
        if self._suspend_main_rebuild:
            return
        model_fn, column = self._get_selection()
        if model_fn and column:
            self._rebuild_model_panel(model_fn, column)

    def _on_components_change(self, change: dict) -> None:
        if not self._can_rebuild_columns or change.get("name") != "value":
            return
        try:
            n = int(change["new"])  # type: ignore[index]
            if n < 1:
                return
        except Exception:
            return

        self._column_cache.clear()
        self._columns = {name: factory for name, factory in self._DEFAULT_COLUMN_FACTORIES.items()}  # type: ignore[union-attr]
        pairs = list(self._columns.items())
        self._column_pairs = pairs
        self._column_picker.widget.options = pairs
        if pairs:
            self._column_picker.set_value(pairs[0][1])

        model_fn, column = self._get_selection()
        if model_fn and column:
            self._rebuild_model_panel(model_fn, column)
        self.set_status(f"<em>Rebuilt columns for {n} component(s).</em>")

    def _open_column_modal(self, _btn):
        # Close any live popover sessions
        if hasattr(self, "_popover_close"):
            try:
                self._popover_close()
            except Exception:
                pass
            try:
                del self._popover_close
            except Exception:
                pass
        if self._toolbar_popover_timer and self._toolbar_popover_timer.is_alive():
            try:
                self._toolbar_popover_timer.cancel()
            except Exception:
                pass

        col_factory = self._column_picker.get_value()
        if col_factory is None:
            self.set_status("<span style='color:#b00'>Pick a column first.</span>")
            return

        self._overlay_dimmer.layout.display = "flex"
        self._suspend_main_rebuild = True
        self._detach_main_observers()

        def build_form_for(factory):
            column = self._column_cache.get(factory) or self._make_column(factory)
            form = self._build_column_form(column)
            def _cache_after_apply(_b):
                self._column_cache[factory] = column
                model_fn, _ = self._get_selection()
                if model_fn is not None:
                    self._rebuild_model_panel(model_fn, column)
                self._column_modal.close()
            form._btn_apply.on_click(_cache_after_apply)  # noqa: SLF001
            return column, form

        column, form = build_form_for(col_factory)
        self._column_modal.open(form.root, title=f"Configure: {getattr(column, 'name', column.__class__.__name__)}")

        def _on_dropdown_change(change: dict):
            if change.get("name") != "value" or not self._column_modal.is_open:
                return
            try:
                column2, form2 = build_form_for(change.get("new"))
                self._column_modal.set_body(form2.root)
                self._column_modal.set_title(f"Configure: {getattr(column2, 'name', column2.__class__.__name__)}")
            except Exception as exc:
                self._column_modal.set_body(W.HTML(f"<span style='color:#b00'>Error: {exc}</span>"))

        self._column_picker.widget.observe(_on_dropdown_change, names="value")

        def _on_modal_close():
            try:
                self._column_picker.widget.unobserve(_on_dropdown_change, names="value")
            except Exception:
                pass
            self._overlay_dimmer.layout.display = "none"
            self._suspend_main_rebuild = False
            self._attach_main_observers()

        self._column_modal.add_close_listener(_on_modal_close)

    # ----- Manual mode -----
    def _on_apply(self, _btn: W.Button) -> None:
        self.set_status("<span style='color:#b00'>Manual mode not implemented.</span>")

    def _on_reset(self, _btn: W.Button) -> None:
        self.set_status("<em>Reset.</em>")