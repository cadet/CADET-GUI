from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    CONCENTRATION_UNITS,
    DEFAULT_BINDING_FACTORIES,
    DEFAULT_COLUMN_FACTORIES,
    MODEL_REGISTRY,
    MULTIPLEXABLE_COLUMN_PARAMS,
    PARAMS,
    batch_elution_spec,
    build_parameter_config_spec,
    lwe_spec,
    require_positive,
)
from .._chrome import style_tag
from ..elements import ChoiceField, ComponentListField, EventTimelineChart, FloatField
from ..forms import FormRenderer

__all__ = ["ConfigurationWidget"]

_CYCLE_TIME_SLIDER_MAX_SECONDS = 300.0 * 60.0

# These templates model a buffer/salt gradient against a load, which is
# meaningless with a single component -- auto-add a second one on selection.
_TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS = frozenset({batch_elution_spec, lwe_spec})


def _round_10sf(v: float) -> float:
    """Round to 10 significant figures, clearing browser-slider float noise."""
    return float(f"{v:.10g}")


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
        self._event_sliders: Dict[str, W.FloatSlider] = {}
        self._cycle_time_minutes_element: Optional[FloatField] = None

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

        self._cycle_time_unit_checkbox = W.Checkbox(
            description="Show Cycle Time in Minutes", value=False, indent=False
        )
        self._cycle_time_unit_checkbox.observe(self._on_cycle_time_unit_change, names="value")

        self._btn_process_settings = W.Button(
            icon="cog", tooltip="Process display settings",
            layout=W.Layout(width="36px", display="none"),
        )
        self._btn_process_settings.on_click(self._on_toggle_process_settings)
        self._process_settings_box = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Settings</div>"),
                self._cycle_time_unit_checkbox,
            ],
            layout=W.Layout(display="none"),
        )
        self._process_settings_box.add_class("cadetgui-section")
        self._process_settings_box.add_class("cadetgui-settings-box")

        self._components = ComponentListField(label="Components:")
        self._component_note = W.HTML(layout=W.Layout(display="none"))
        self._component_note.add_class("cadetgui-note")
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
        self._event_plot_label = W.HTML("<div class='cadetgui-section-title'>Event Timeline</div>")
        self._event_chart = EventTimelineChart()
        self.status = W.HTML("<em>Select a column and model.</em>")
        self.status.add_class("cadetgui-status")

        self._btn_export = W.Button(description="Export script", icon="code")
        self._script_out = W.Textarea(layout=W.Layout(width="100%", height="220px", display="none"))
        self._script_out.add_class("cadetgui-script")

        components_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Component System</div>"),
                self._components,
                self._component_note,
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
        column_section.add_class("cadetgui-section-half")

        binding_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Binding Model</div>"),
                self._binding_picker,
                self._binding_form_box,
            ]
        )
        binding_section.add_class("cadetgui-section")
        binding_section.add_class("cadetgui-section-half")

        column_binding_row = W.HBox([column_section, binding_section])
        column_binding_row.add_class("cadetgui-row")

        process_header = W.HBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Process</div>"),
                self._btn_process_settings,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )

        model_form_column = W.VBox([self._model_form_box])
        model_form_column.add_class("cadetgui-section-half")

        event_chart_column = W.VBox([self._event_plot_label, self._event_chart])
        event_chart_column.add_class("cadetgui-section-half")

        process_columns = W.HBox([model_form_column, event_chart_column])
        process_columns.add_class("cadetgui-row")

        process_section = W.VBox(
            [
                process_header,
                self._process_settings_box,
                self._model_picker,
                process_columns,
            ]
        )
        process_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                components_section,
                column_binding_row,
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
        self._model_picker.observe(self._on_model_selection_change, names="selected_index")
        self._btn_export.on_click(self._on_export)

        self._sync_component_minimum()
        if not self._maybe_autoadd_component():
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
        # Keyed by id(column): a binding model's component_system must be the same
        # object as its column's, and each column gets its own.
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

    def _on_model_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._sync_component_minimum()
        if self._maybe_autoadd_component():
            return  # setting self._components.value already rebuilt the forms
        self._rebuild_forms()

    def _required_min_components(self) -> int:
        model_fn = self._model_picker.value
        return 2 if model_fn in _TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS else 1

    def _sync_component_minimum(self) -> None:
        """Raise/lower the component list's floor to match the selected template.

        Also drives the info note next to it and (via `min_components`) greys
        out the list's remove button once the row count hits the floor.
        """
        required = self._required_min_components()
        self._components.min_components = required
        if required > 1:
            self._component_note.value = (
                "The process template you selected does not allow less than"
                f" {required} components."
            )
            self._component_note.layout.display = ""
        else:
            self._component_note.layout.display = "none"

    def _maybe_autoadd_component(self) -> bool:
        """Add a second component when a gradient template needs one but only one exists."""
        required = self._required_min_components()
        names = self._components.value
        if len(names) < required:
            self._components.value = [
                *names,
                *(f"Component {i}" for i in range(len(names) + 1, required + 1)),
            ]
            return True
        return False

    def _on_toggle_settings(self, _btn: Any) -> None:
        shown = self._settings_box.layout.display != "none"
        self._settings_box.layout.display = "none" if shown else ""

    def _on_toggle_process_settings(self, _btn: Any) -> None:
        shown = self._process_settings_box.layout.display != "none"
        self._process_settings_box.layout.display = "none" if shown else ""

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
            self._clear_event_section()
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
        self._rebuild_event_sliders()

        self.status.value = (
            "<em>Fields apply automatically as you edit them"
            " (column and binding model first, since the process picks up"
            " whatever's currently set on them).</em>"
        )

    def _clear_event_section(self) -> None:
        self._event_sliders = {}
        self._cycle_time_minutes_element = None
        self._event_chart.series = []

    def _rebuild_event_sliders(self) -> None:
        """Add a slider next to each scalar timing/flow field.

        Only `float`-kind fields get a slider; per-component concentration
        fields stay list-editors. Each slider is dlinked to its field's
        value, so a slider move commits through the form exactly like typing
        a new value would.
        """
        self._event_sliders = {}
        self._cycle_time_minutes_element = None
        if self._model_form is None:
            self._clear_event_section()
            return

        has_cycle_time = any(f.name == "cycle_time" for f in self._model_form.spec.fields)
        self._btn_process_settings.layout.display = "" if has_cycle_time else "none"
        if not has_cycle_time:
            self._process_settings_box.layout.display = "none"

        for f in self._model_form.spec.fields:
            if f.kind != "float":
                continue
            el = self._model_form.element(f.name)
            default = float(el.value)
            if f.name == "cycle_time":
                slider_max = max(default, _CYCLE_TIME_SLIDER_MAX_SECONDS)
            else:
                slider_max = default * 5 if default > 0 else 1.0
            # step=default/100 keeps the default on the slider's step grid;
            # otherwise the browser snaps it to the nearest step on render and
            # reports that back, silently overwriting the default.
            step = default / 100 if default > 0 else 0.01
            slider = W.FloatSlider(
                value=default,
                min=0.0,
                max=slider_max,
                step=step,
                readout=False,  # the linked field already shows the value
                layout=W.Layout(width="100%", max_width="200px", min_width="100px"),
            )
            # dlink+round, not link: slider drag reports float noise (e.g.
            # 19620.00000000004) that a plain link would pass straight through.
            W.dlink((slider, "value"), (el, "value"), transform=_round_10sf)
            W.dlink((el, "value"), (slider, "value"), transform=_round_10sf)
            slider.observe(lambda _change: self._redraw_event_plot(), names="value")
            self._event_sliders[f.name] = slider

        new_children = []
        for child in self._model_form.root.children:
            matched = next(
                (
                    f
                    for f in self._model_form.spec.fields
                    if child is self._model_form.element(f.name)
                ),
                None,
            )
            extras: list = []
            if matched is not None and matched.name == "cycle_time":
                extras.append(self._make_cycle_time_unit_toggle(child))
            if matched is not None and matched.name in self._event_sliders:
                extras.append(self._event_sliders[matched.name])

            if extras:
                # HBox defaults to nowrap, which would overlap the slider
                # instead of wrapping it on a narrow window.
                pair_row = W.HBox(
                    [child, *extras],
                    layout=W.Layout(flex_flow="row wrap", align_items="center"),
                )
                new_children.append(pair_row)
            else:
                new_children.append(child)
        self._model_form.root.children = tuple(new_children)

        self._event_plot_label.layout.display = "" if self._event_sliders else "none"
        self._redraw_event_plot()

    def _make_cycle_time_unit_toggle(self, seconds_element: Any) -> Any:
        """Companion minutes field for Cycle time, shown/hidden by the process settings checkbox.

        `seconds_element` is the real field feeding `collect_values()` /
        CADET-Process and always stays in seconds; the companion field is
        dlinked to it in both directions so they stay in sync regardless of
        which one is currently visible.
        """
        minutes_element = FloatField(
            label=seconds_element.label,
            value=float(seconds_element.value) / 60.0,
            units="min",
            validate=require_positive,
        )
        W.dlink(
            (seconds_element, "value"), (minutes_element, "value"), transform=lambda s: s / 60.0
        )
        W.dlink(
            (minutes_element, "value"), (seconds_element, "value"), transform=lambda m: m * 60.0
        )

        self._cycle_time_minutes_element = minutes_element
        self._apply_cycle_time_unit_display()
        return minutes_element

    def _on_cycle_time_unit_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self._apply_cycle_time_unit_display()

    def _apply_cycle_time_unit_display(self) -> None:
        if self._cycle_time_minutes_element is None or self._model_form is None:
            return
        seconds_element = self._model_form.element("cycle_time")
        show_minutes = self._cycle_time_unit_checkbox.value
        seconds_element.layout.display = "none" if show_minutes else ""
        self._cycle_time_minutes_element.layout.display = "" if show_minutes else "none"

    def _redraw_event_plot(self) -> None:
        """Feed the interactive chart raw values from `Process.parameter_timelines`.

        Reuses the form's own already-committed build rather than building
        again here.
        """
        if self._model_form is None or self._model_form.built is None:
            return
        process = self._model_form.built
        try:
            cycle_time = float(process.cycle_time)
            if cycle_time <= 0:
                self._event_chart.series = []
                return
            n_samples = 300
            times_s = [cycle_time * i / (n_samples - 1) for i in range(n_samples)]
            times_min = [t / 60.0 for t in times_s]

            series = []
            for name, timeline in process.parameter_timelines.items():
                raw = timeline.value(times_s)
                raw = raw.tolist() if hasattr(raw, "tolist") else list(raw)
                n_cols = len(raw[0]) if raw and isinstance(raw[0], (list, tuple)) else 1
                # Legend shows the unit-op name ("Eluent"), not the full dotted
                # path ("flow_sheet.eluent.flow_rate"); the quantity goes on
                # the axis instead (below).
                parts = name.split(".")
                unit_op = parts[-2] if len(parts) >= 2 else name
                display_name = unit_op.replace("_", " ").capitalize()
                component_names = self._components.value
                for col in range(n_cols):
                    if n_cols == 1:
                        label = display_name
                    elif col < len(component_names):
                        label = f"{display_name} ({component_names[col]})"
                    else:
                        label = f"{display_name} [{col}]"
                    values = [
                        float(row[col]) if isinstance(row, (list, tuple)) else float(row)
                        for row in raw
                    ]
                    series.append({"name": label, "times": times_min, "values": values})

            quantities = {name.split(".")[-1] for name in process.parameter_timelines}
            if len(quantities) == 1:
                quantity = next(iter(quantities))
                quantity_units = {
                    "flow_rate": PARAMS["flow_rate"].units,
                    "c": CONCENTRATION_UNITS,
                }
                units = quantity_units.get(quantity)
                if quantity == "c":
                    label = "Concentration"
                else:
                    label = quantity.replace("_", " ").capitalize()
                self._event_chart.y_label = f"{label} / {units}" if units else label
            else:
                self._event_chart.y_label = "state"
            self._event_chart.series = series
        except Exception:
            return

    def export_script(self) -> str:
        """Generate an executable CADET-Process Python script for the current build.

        Introspects the built objects' classes rather than a hardcoded
        column/model/binding mapping, so it works for anything registered.
        """
        if (
            self.process is None
            or self._column_form is None
            or self._binding_form is None
            or self._model_form is None
        ):
            raise RuntimeError(
                "Nothing built yet — pick a column, binding model, and process template first."
            )

        column = self._get_column()
        binding_model = self._get_binding_model()
        cs_cls = ComponentSystem
        col_cls = type(column)
        bind_cls = type(binding_model)
        proc_cls = type(self.process)
        model_spec = self._model_form.spec

        imports = [
            f"from {cs_cls.__module__} import {cs_cls.__name__}",
            f"from {col_cls.__module__} import {col_cls.__name__}",
            f"from {bind_cls.__module__} import {bind_cls.__name__}",
            f"from {proc_cls.__module__} import {proc_cls.__name__}",
        ]
        if model_spec.export is not None:
            imports.append("from CADETProcess.processModel import FlowSheet, Inlet, Outlet")

        lines = [
            *imports,
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

        model_values = self._model_form.collect_values()
        if model_spec.export is not None:
            lines.extend(model_spec.export(model_values))
        else:
            lines.append("")
            lines.append(f"process = {proc_cls.__name__}(")
            lines.append("    column=column,")
            for name, value in model_values.items():
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
