from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    BYPASSABLE_UNITS,
    CONCENTRATION_UNITS,
    INSTRUMENT_TEMPLATES,
    MULTIPLEXABLE_COLUMN_PARAMS,
    PARAMS,
    build_parameter_config_spec,
    lwe_spec,
    require_positive,
    step_elution_spec,
)
from ...configuration_store import ConfigurationState
from .._chrome import style_tag
from .._settings_popover import SettingsPopover
from ..elements import (
    ChoiceField,
    EventTimelineChart,
    FloatField,
)
from ..forms import FormRenderer
from .configuration_persistence import ConfigurationPersistence
from .instrument import InstrumentWidget

__all__ = ["ConfigurationWidget"]

_CYCLE_TIME_SLIDER_MAX_SECONDS = 300.0 * 60.0
_DEFAULT_CONFIG_NAME = "New Experiment"

# These templates model a buffer/salt gradient against a load/sample, which is
# meaningless with a single component -- auto-add a second one on selection.
# Pulse Injection/Step/Breakthrough stay single-component-friendly on purpose
# (a non-binding tracer pulse is the standard characterization experiment).
_TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS = frozenset({lwe_spec, step_elution_spec})


def _round_10sf(v: float) -> float:
    """Round to 10 significant figures, clearing browser-slider float noise."""
    return float(f"{v:.10g}")


def _key_for_value(registry: Mapping[str, Any], value: Any) -> Optional[str]:
    """Reverse-lookup a registry's human label for one of its factory values."""
    return next((k for k, v in registry.items() if v == value), None)


class ConfigurationWidget:
    """Pick a process template and configure it against a bound InstrumentWidget.

    Column/binding *type* and topology live on the bound `InstrumentWidget`
    (see `bind_to_instrument`); this widget renders their *parameter* forms
    (against `instrument.flow_sheet.column`/`.column.binding_model`) plus the
    process-template form. Rebuilds whenever the bound instrument or the
    process-template selection changes. `.process` holds the latest
    successfully-built object; `add_listener` registers a callback that fires
    with it on every successful build.
    """

    def __init__(
        self,
        *,
        instrument: Optional[InstrumentWidget] = None,
        registry: Optional[Dict[str, Callable[[LCFlowSheet], Any]]] = None,
    ) -> None:
        self._registry = registry or INSTRUMENT_TEMPLATES
        self._instrument: Optional[InstrumentWidget] = None
        self._listeners: List[Callable[[Any], None]] = []
        self.process: Any = None
        self._column_form: Optional[FormRenderer] = None
        self._binding_form: Optional[FormRenderer] = None
        self._model_form: Optional[FormRenderer] = None
        self._event_sliders: Dict[str, W.FloatSlider] = {}
        self._cycle_time_minutes_element: Optional[FloatField] = None
        # Set around _apply_state()'s picker writes so each one's own observer
        # doesn't trigger its own full rebuild -- one rebuild for the whole
        # restored selection instead of one per field touched.
        self._suspend_rebuild = False

        # Column Model gear popover: "Show optional parameters" + one "Enable
        # ... Multiplex" checkbox per multiplexable column parameter.
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

        self._show_optional_column_checkbox = W.Checkbox(
            description="Show optional parameters", value=False, indent=False
        )
        self._show_optional_column_checkbox.observe(self._on_show_optional_change, names="value")

        self._column_settings = SettingsPopover(
            tooltip="Column settings",
            children=[self._show_optional_column_checkbox, *self._multiplex_checkboxes.values()],
        )

        # Binding Model gear popover.
        self._show_optional_binding_checkbox = W.Checkbox(
            description="Show optional parameters", value=False, indent=False
        )
        self._show_optional_binding_checkbox.observe(self._on_show_optional_change, names="value")
        self._binding_settings = SettingsPopover(
            tooltip="Binding settings", children=[self._show_optional_binding_checkbox]
        )

        # Process gear popover -- only shown for a template with a cycle_time
        # field (see _rebuild_event_sliders).
        self._cycle_time_unit_checkbox = W.Checkbox(
            description="Show Cycle Time in Minutes", value=False, indent=False
        )
        self._cycle_time_unit_checkbox.observe(self._on_cycle_time_unit_change, names="value")
        self._process_settings = SettingsPopover(
            tooltip="Process display settings",
            children=[self._cycle_time_unit_checkbox],
            visible=False,
        )

        self._model_picker = ChoiceField(
            label="Process Template:", options=list(self._registry.items())
        )

        # Empty boxes filled in by _rebuild_forms() with each FormRenderer's
        # rendered fields once an instrument/template is available.
        self._column_form_box = W.VBox([])
        self._binding_form_box = W.VBox([])
        self._model_form_box = W.VBox([])
        # Right-hand column of the Process section: the interactive event/
        # flow-rate-over-time chart, redrawn on every slider move.
        self._event_plot_label = W.HTML("<div class='cadetgui-section-title'>Event Timeline</div>")
        self._event_chart = EventTimelineChart()
        # Status line at the very bottom of the panel.
        self.status = W.HTML("<em>Bind an Instrument to get started.</em>")
        self.status.add_class("cadetgui-status")

        # "Export script" button + the generated-script textarea below it.
        self._btn_export = W.Button(description="Export script", icon="code")
        self._script_out = W.Textarea(layout=W.Layout(width="100%", height="220px", display="none"))
        self._script_out.add_class("cadetgui-script")

        # Renders as the "Save / Load Configuration" section at the top of the panel.
        self.persistence = ConfigurationPersistence(
            default_name=_DEFAULT_CONFIG_NAME,
            snapshot=self._snapshot_state,
            apply_state=self._apply_state,
            get_process=lambda: self.process,
            on_name_change=lambda _name: self._notify(),  # e.g. the Simulation tab's process label
        )

        column_header = W.HBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Column Model</div>"),
                self._column_settings.button,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )
        column_section = W.VBox(
            [
                column_header,
                self._column_settings.box,
                self._column_form_box,
            ]
        )
        column_section.add_class("cadetgui-section")
        column_section.add_class("cadetgui-section-half")

        binding_header = W.HBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Binding Model</div>"),
                self._binding_settings.button,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )
        binding_section = W.VBox(
            [
                binding_header,
                self._binding_settings.box,
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
                self._process_settings.button,
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
                self._process_settings.box,
                self._model_picker,
                process_columns,
            ]
        )
        process_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                self.persistence.root,
                column_binding_row,
                process_section,
                self._btn_export,
                self._script_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._model_picker.observe(self._on_model_selection_change, names="selected_index")
        self._btn_export.on_click(self._on_export)

        if instrument is not None:
            self.bind_to_instrument(instrument)

    def bind_to_instrument(self, instrument: InstrumentWidget) -> None:
        """Track an InstrumentWidget's built flow sheet automatically."""
        self._instrument = instrument
        instrument.add_listener(self._on_instrument_changed)
        self._sync_component_minimum()
        if not self._maybe_autoadd_component():
            self._rebuild_forms()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.process` on every build or name change."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.process)

    @property
    def flow_sheet(self) -> Optional[LCFlowSheet]:
        """The bound instrument's current flow sheet, or None if unbound/unbuilt."""
        return self._instrument.flow_sheet if self._instrument is not None else None

    @property
    def components(self) -> List[str]:
        """The bound instrument's current component names, or [] if unbound."""
        return self._instrument.components if self._instrument is not None else []

    def _get_column(self) -> Any:
        flow_sheet = self.flow_sheet
        return getattr(flow_sheet, "column", None) if flow_sheet is not None else None

    def _get_binding_model(self) -> Any:
        column = self._get_column()
        return getattr(column, "binding_model", None) if column is not None else None

    def _on_instrument_changed(self, _flow_sheet: Any) -> None:
        if self._suspend_rebuild:
            return
        self._sync_component_minimum()
        if self._maybe_autoadd_component():
            return  # setting instrument.components already rebuilt the forms
        self._rebuild_forms()

    def _on_model_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._sync_component_minimum()
        if self._maybe_autoadd_component():
            return  # setting instrument.components already rebuilt the forms
        self._rebuild_forms()

    def _required_min_components(self) -> int:
        model_fn = self._model_picker.value
        return 2 if model_fn in _TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS else 1

    def _sync_component_minimum(self) -> None:
        """Raise/lower the bound instrument's component-list floor to match the template."""
        if self._instrument is None:
            return
        self._instrument.set_min_components(self._required_min_components())

    def _maybe_autoadd_component(self) -> bool:
        """Add a second component when a gradient template needs one but only one exists."""
        if self._instrument is None:
            return False
        required = self._required_min_components()
        names = self._instrument.components
        if len(names) < required:
            self._instrument.components = [
                *names,
                *(f"Component {i}" for i in range(len(names) + 1, required + 1)),
            ]
            return True
        return False

    def _make_on_multiplex_change(self, name: str) -> Callable[[dict], None]:
        def _on_change(change: dict) -> None:
            if change.get("name") != "value":
                return
            self._multiplex_state[name] = bool(change["new"])
            self._rebuild_forms()

        return _on_change

    def _on_show_optional_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self._rebuild_forms()

    def _on_process_built(self, built: Any) -> None:
        self.process = built
        self.persistence.refresh_hash_display()
        self._notify()
        self.status.value = "<em>Process built.</em>"

    def _snapshot_state(self) -> ConfigurationState:
        """Capture the current selection + field values as the hashed save/import payload.

        `_column_form`/`_binding_form` are legitimately `None` when the
        instrument bypasses the column entirely -- only `_model_form` (the
        process itself) is required.
        """
        if self._instrument is None or self._model_form is None:
            raise RuntimeError(
                "Nothing built yet -- bind an Instrument and pick a template first."
            )
        template_key = _key_for_value(self._registry, self._model_picker.value)
        if template_key is None:
            raise RuntimeError("Current selection isn't in a known registry -- can't snapshot it.")
        return ConfigurationState(
            instrument=self._instrument.snapshot(),
            template_key=template_key,
            multiplex_state=dict(self._multiplex_state),
            show_optional_column=bool(self._show_optional_column_checkbox.value),
            show_optional_binding=bool(self._show_optional_binding_checkbox.value),
            column_values=self._column_form.collect_values() if self._column_form else {},
            binding_values=self._binding_form.collect_values() if self._binding_form else {},
            model_values=self._model_form.collect_values(),
        )

    @property
    def config_name(self) -> str:
        """Name shown in the Save/Load section and used as the save target."""
        return self.persistence.config_name

    @config_name.setter
    def config_name(self, value: str) -> None:
        self.persistence.config_name = value

    @property
    def config_hash(self) -> Optional[str]:
        """Content hash of the current configuration, or None if nothing is built yet."""
        return self.persistence.config_hash

    def name_error(self, action: str = "saving") -> Optional[str]:
        """Error message if this configuration has no name yet for `action`, else None."""
        return self.persistence.name_error(action)

    def persist_to_store(self) -> Path:
        """Snapshot and save the current configuration to the store. Returns its path.

        Raises RuntimeError if unnamed or nothing has been built yet.
        """
        return self.persistence.persist_to_store()

    def import_from_store(self, hash_: str) -> None:
        """Load a configuration previously saved to the local store, by its hash."""
        self.persistence.import_from_store(hash_)

    def _apply_state(self, name: str, state: ConfigurationState) -> None:
        """Reconstruct the bound instrument/pickers/forms from a saved ConfigurationState."""
        if self._instrument is None:
            raise RuntimeError("No Instrument bound -- call bind_to_instrument() first.")
        template_factory = self._registry.get(state.template_key)
        if template_factory is None:
            raise ValueError(
                "Saved configuration references a process template"
                " that isn't registered here anymore."
            )

        self._suspend_rebuild = True
        try:
            for param_name, enabled in state.multiplex_state.items():
                checkbox = self._multiplex_checkboxes.get(param_name)
                if checkbox is not None:
                    checkbox.value = enabled
            self._show_optional_column_checkbox.value = state.show_optional_column
            self._show_optional_binding_checkbox.value = state.show_optional_binding
            self._instrument.apply_state(state.instrument)
            self._model_picker.value = template_factory
        finally:
            self._suspend_rebuild = False

        self._rebuild_forms()
        if self._column_form is not None:
            self._column_form.set_values(state.column_values)
        if self._binding_form is not None:
            self._binding_form.set_values(state.binding_values)
        self._model_form.set_values(state.model_values)

        self.persistence.set_name(name)

    def _rebuild_forms(self) -> None:
        if self._suspend_rebuild:
            return
        column = self._get_column()
        binding_model = self._get_binding_model()
        model_fn = self._model_picker.value
        flow_sheet = self.flow_sheet
        if flow_sheet is None or model_fn is None:
            self._column_form_box.children = ()
            self._binding_form_box.children = ()
            self._model_form_box.children = ()
            self._clear_event_section()
            self.persistence.refresh_hash_display()
            return

        if column is not None:
            column_params = set(getattr(column, "required_parameters", None) or [])
            applicable = column_params & MULTIPLEXABLE_COLUMN_PARAMS
            for name, checkbox in self._multiplex_checkboxes.items():
                checkbox.layout.display = "" if name in applicable else "none"

            self._column_form = FormRenderer(
                build_parameter_config_spec(
                    column,
                    multiplex=self._multiplex_state,
                    include_optional=self._show_optional_column_checkbox.value,
                )
            )
            self._column_form_box.children = (self._column_form.root,)
        else:
            self._column_form = None
            self._column_form_box.children = ()

        if binding_model is not None:

            def _attach_binding(built: Any, col: Any = column) -> None:
                col.binding_model = built

            self._binding_form = FormRenderer(
                build_parameter_config_spec(
                    binding_model, include_optional=self._show_optional_binding_checkbox.value
                ),
                on_built=_attach_binding,
            )
            self._binding_form_box.children = (self._binding_form.root,)
        else:
            self._binding_form = None
            self._binding_form_box.children = ()

        self._model_form = FormRenderer(model_fn(flow_sheet), on_built=self._on_process_built)
        self._model_form_box.children = (self._model_form.root,)
        self._rebuild_event_sliders()
        # The model form's own on_built=_on_process_built fires from inside the
        # FormRenderer(...) constructor call above, before this method's own
        # `self._model_form = ...` assignment has completed -- so that first
        # call sees a stale (pre-rebuild) _model_form and can't snapshot yet.
        # Refresh again now that all three forms are actually assigned.
        self.persistence.refresh_hash_display()

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
        self._process_settings.visible = has_cycle_time

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
                component_names = self._instrument.components if self._instrument else []
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
            or self._instrument is None
            or self._instrument.flow_sheet is None
            or self._model_form is None
        ):
            raise RuntimeError(
                "Nothing built yet — bind an Instrument and pick a process template first."
            )

        flow_sheet = self._instrument.flow_sheet
        column = self._get_column()
        binding_model = self._get_binding_model()
        cs_cls = ComponentSystem
        proc_cls = type(self.process)
        state = self._instrument.snapshot()

        imports = [
            f"from {cs_cls.__module__} import {cs_cls.__name__}",
            f"from {LCFlowSheet.__module__} import LCFlowSheet",
        ]
        if column is not None:
            col_cls = type(column)
            imports.append(f"from {col_cls.__module__} import {col_cls.__name__}")
        if binding_model is not None:
            bind_cls = type(binding_model)
            imports.append(f"from {bind_cls.__module__} import {bind_cls.__name__}")
        imports.append(f"from {proc_cls.__module__} import {proc_cls.__name__}")

        lines = [
            *imports,
            "",
            f"component_system = {cs_cls.__name__}({state.components!r})",
            "",
        ]

        flow_sheet_kwargs = ["component_system"]
        if state.include_sample_loop:
            flow_sheet_kwargs.append(f"sample_loop_volume={state.sample_loop_volume!r}")
            if not state.sample_loop_diameter_auto:
                flow_sheet_kwargs.append(f"sample_loop_diameter={state.sample_loop_diameter!r}")
        if column is not None:
            flow_sheet_kwargs.append(f"ColumnModel={type(column).__name__}")
        if binding_model is not None:
            flow_sheet_kwargs.append(f"BindingModel={type(binding_model).__name__}")
        if state.bypass_units:
            flow_sheet_kwargs.append(f"bypass_units={state.bypass_units!r}")
        lines.append("flow_sheet = LCFlowSheet(" + ", ".join(flow_sheet_kwargs) + ")")

        # Mixer/tubing dead-volume geometry has no parameter form (see
        # instrument.py's seeding note) -- emit its live values directly.
        for unit_name in BYPASSABLE_UNITS:
            if unit_name == "column":
                continue
            unit = getattr(flow_sheet, unit_name, None)
            if unit is None:
                continue
            lines.append("")
            for pname in unit.required_parameters:
                lines.append(f"flow_sheet.{unit_name}.{pname} = {getattr(unit, pname)!r}")

        if column is not None:
            lines.append("")
            for name, value in self._column_form.collect_values().items():
                lines.append(f"flow_sheet.column.{name} = {value!r}")

        if binding_model is not None:
            lines.append("")
            for name, value in self._binding_form.collect_values().items():
                lines.append(f"flow_sheet.column.binding_model.{name} = {value!r}")

        model_values = self._model_form.collect_values()
        lines.append("")
        lines.append(f"process = {proc_cls.__name__}({self.process.name!r}, flow_sheet,")
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
