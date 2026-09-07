# =========================================
# File: cadetgui/widgets/composite/configuration.py
# =========================================
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    DEFAULT_BINDING_FACTORIES,
    DEFAULT_COLUMN_FACTORIES,
    MODEL_REGISTRY,
    MULTIPLEXABLE_COLUMN_PARAMS,
    build_parameter_config_spec,
)
from .._chrome import style_tag
from ..elements import ChoiceField, ComponentListField
from ..forms import FormRenderer

__all__ = ["ConfigurationWidget"]


class ConfigurationWidget:
    """Pick a unit operation + binding model + model-builder template, build a process.

    Rebuilds its forms whenever the component count, column, binding model, or
    process-template selection changes. `.process` holds the latest
    successfully-built object; `add_listener` registers a callback that fires
    with it on every successful build.
    """

    def __init__(
        self,
        *,
        registry: Optional[Dict[str, Callable[[Any], Any]]] = None,
        columns: Optional[Dict[str, Callable[[ComponentSystem], Any]]] = None,
        binding_registry: Optional[Dict[str, Callable[[ComponentSystem], Any]]] = None,
    ) -> None:
        self._registry = registry or MODEL_REGISTRY
        self._columns = columns or DEFAULT_COLUMN_FACTORIES
        self._binding_registry = binding_registry or DEFAULT_BINDING_FACTORIES
        self._column_cache: Dict[Any, Any] = {}
        self._binding_cache: Dict[Any, Any] = {}
        self._listeners: List[Callable[[Any], None]] = []
        self.process: Any = None
        self._column_form: Optional[FormRenderer] = None
        self._binding_form: Optional[FormRenderer] = None
        self._model_form: Optional[FormRenderer] = None

        self._multiplex_state: Dict[str, bool] = dict.fromkeys(MULTIPLEXABLE_COLUMN_PARAMS, False)
        self._multiplex_checkboxes: Dict[str, W.Checkbox] = {
            name: W.Checkbox(
                description=f"Enable {name.replace('_', ' ').title()} Multiplex",
                value=False,
                indent=False,
            )
            for name in MULTIPLEXABLE_COLUMN_PARAMS
        }
        for name, checkbox in self._multiplex_checkboxes.items():
            checkbox.observe(self._make_on_multiplex_change(name), names="value")

        self._btn_settings = W.Button(
            icon="cog", tooltip="Column discretization settings",
            layout=W.Layout(width="36px"),
        )
        self._btn_settings.on_click(self._on_toggle_settings)
        self._settings_box = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Settings</div>"),
                *self._multiplex_checkboxes.values(),
            ],
            layout=W.Layout(display="none"),
        )
        self._settings_box.add_class("cadetgui-section")
        self._settings_box.add_class("cadetgui-settings-box")

        self._components = ComponentListField(label="Components:")
        self._column_picker = ChoiceField(
            label="Column Model:", options=list(self._columns.items())
        )
        self._binding_picker = ChoiceField(
            label="Binding Model:", options=list(self._binding_registry.items())
        )
        self._model_picker = ChoiceField(
            label="Process Template:", options=list(self._registry.items())
        )

        self._column_form_box = W.VBox([])
        self._binding_form_box = W.VBox([])
        self._model_form_box = W.VBox([])
        self.status = W.HTML("<em>Select a column and model.</em>")
        self.status.add_class("cadetgui-status")

        self._btn_export = W.Button(description="Export script", icon="code")
        self._script_out = W.Textarea(layout=W.Layout(width="100%", height="220px", display="none"))
        self._script_out.add_class("cadetgui-script")

        components_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Component System</div>"),
                self._components,
            ]
        )
        components_section.add_class("cadetgui-section")

        column_header = W.HBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Column Model</div>"),
                self._btn_settings,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )
        column_section = W.VBox(
            [
                column_header,
                self._settings_box,
                self._column_picker,
                self._column_form_box,
            ]
        )
        column_section.add_class("cadetgui-section")

        binding_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Binding Model</div>"),
                self._binding_picker,
                self._binding_form_box,
            ]
        )
        binding_section.add_class("cadetgui-section")

        process_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Process</div>"),
                self._model_picker,
                self._model_form_box,
            ]
        )
        process_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                components_section,
                column_section,
                binding_section,
                process_section,
                self._btn_export,
                self._script_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._components.observe(self._on_components_change, names="value")
        self._column_picker.observe(self._on_selection_change, names="selected_index")
        self._binding_picker.observe(self._on_selection_change, names="selected_index")
        self._model_picker.observe(self._on_selection_change, names="selected_index")
        self._btn_export.on_click(self._on_export)

        self._rebuild_forms()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.process` on every successful build."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.process)

    def _get_column(self) -> Any:
        factory = self._column_picker.value
        if factory is None:
            return None
        if factory not in self._column_cache:
            cs = ComponentSystem(self._components.value)
            self._column_cache[factory] = factory(cs)
        return self._column_cache[factory]

    def _get_binding_model(self) -> Any:
        factory = self._binding_picker.value
        column = self._get_column()
        if factory is None or column is None:
            return None
        # Keyed by (factory, id(column)) rather than just factory: a binding
        # model's component_system must be the *same object* as its column's
        # (CADET-Process raises "Component systems do not match" otherwise),
        # and each distinct column instance gets its own ComponentSystem — so
        # a binding model cached against a since-replaced column would no
        # longer be attachable to the current one.
        cache_key = (factory, id(column))
        if cache_key not in self._binding_cache:
            self._binding_cache[cache_key] = factory(column.component_system)
        return self._binding_cache[cache_key]

    def _on_components_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self._column_cache.clear()
        self._binding_cache.clear()
        self._rebuild_forms()

    def _on_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._rebuild_forms()

    def _on_toggle_settings(self, _btn: Any) -> None:
        shown = self._settings_box.layout.display != "none"
        self._settings_box.layout.display = "none" if shown else ""

    def _make_on_multiplex_change(self, name: str) -> Callable[[dict], None]:
        def _on_change(change: dict) -> None:
            if change.get("name") != "value":
                return
            self._multiplex_state[name] = bool(change["new"])
            self._rebuild_forms()

        return _on_change

    def _on_process_built(self, built: Any) -> None:
        self.process = built
        self._notify()
        self.status.value = "<em>Process built.</em>"

    def _rebuild_forms(self) -> None:
        column = self._get_column()
        binding_model = self._get_binding_model()
        model_fn = self._model_picker.value
        if column is None or binding_model is None or model_fn is None:
            self._column_form_box.children = ()
            self._binding_form_box.children = ()
            self._model_form_box.children = ()
            return

        column_params = set(getattr(column, "required_parameters", None) or [])
        applicable = column_params & MULTIPLEXABLE_COLUMN_PARAMS
        for name, checkbox in self._multiplex_checkboxes.items():
            checkbox.layout.display = "" if name in applicable else "none"
        self._btn_settings.layout.display = "" if applicable else "none"
        if not applicable:
            self._settings_box.layout.display = "none"

        self._column_form = FormRenderer(
            build_parameter_config_spec(column, multiplex=self._multiplex_state)
        )
        self._column_form_box.children = (self._column_form.root,)

        def _attach_binding(built: Any, col: Any = column) -> None:
            col.binding_model = built

        self._binding_form = FormRenderer(
            build_parameter_config_spec(binding_model), on_built=_attach_binding
        )
        self._binding_form_box.children = (self._binding_form.root,)

        self._model_form = FormRenderer(model_fn(column), on_built=self._on_process_built)
        self._model_form_box.children = (self._model_form.root,)

        self.status.value = (
            "<em>Configure the column, binding model, and process, then Apply each"
            " (in that order — the process picks up whatever's applied on column"
            " and binding model at the time).</em>"
        )

    def export_script(self) -> str:
        """Generate an executable CADET-Process Python script for the current build.

        Introspects the actual built objects' classes (`type(obj).__module__` /
        `__name__`) rather than a hardcoded column/model/binding name mapping, so
        this works for anything registered — no per-type special-casing
        (PRODUCT_VISION.md ARCH-003: the "expert escape hatch"/anti-black-box
        requirement).
        """
        if (
            self.process is None
            or self._column_form is None
            or self._binding_form is None
            or self._model_form is None
        ):
            raise RuntimeError(
                "Nothing built yet — Apply the column, binding model, and process forms first."
            )

        column = self._get_column()
        binding_model = self._get_binding_model()
        cs_cls = ComponentSystem
        col_cls = type(column)
        bind_cls = type(binding_model)
        proc_cls = type(self.process)

        lines = [
            f"from {cs_cls.__module__} import {cs_cls.__name__}",
            f"from {col_cls.__module__} import {col_cls.__name__}",
            f"from {bind_cls.__module__} import {bind_cls.__name__}",
            f"from {proc_cls.__module__} import {proc_cls.__name__}",
            "",
            f"component_system = {cs_cls.__name__}({self._components.value!r})",
            "",
            f"column = {col_cls.__name__}(component_system, name={column.name!r})",
        ]
        for name, value in self._column_form.collect_values().items():
            lines.append(f"column.{name} = {value!r}")

        lines.append("")
        lines.append(
            f"column.binding_model = {bind_cls.__name__}("
            f"component_system, name={binding_model.name!r})"
        )
        for name, value in self._binding_form.collect_values().items():
            lines.append(f"column.binding_model.{name} = {value!r}")

        lines.append("")
        lines.append(f"process = {proc_cls.__name__}(")
        lines.append("    column=column,")
        for name, value in self._model_form.collect_values().items():
            lines.append(f"    {name}={value!r},")
        lines.append(")")

        return "\n".join(lines)

    def _on_export(self, _btn: Any) -> None:
        try:
            script = self.export_script()
        except RuntimeError as exc:
            self.status.value = f"<span style='color:#b00020'>{exc}</span>"
            return
        self._script_out.value = script
        self._script_out.layout.display = ""
        self.status.value = "<em>Script generated below.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
