from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    BINDING_MODELS,
    BYPASSABLE_UNITS,
    COLUMN_MODELS,
    CONCENTRATION_UNITS,
    INSTRUMENT_COMPATIBLE_COLUMNS,
    INSTRUMENT_TEMPLATES,
    MULTIPLEXABLE_COLUMN_PARAMS,
    PARAMS,
    STANDALONE_TEMPLATES,
    active_inlets,
    build_parameter_config_spec,
    lwe_spec,
    require_positive,
    step_elution_spec,
    template_required_units,
)
from ...configuration_store import ConfigurationState
from .._chrome import style_tag
from .._settings_popover import SettingsPopover
from .._status import status_html
from ..elements import (
    ChoiceField,
    ComponentListField,
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
# Pulse Injection/Step/Breakthrough/Pulse Feed stay single-component-friendly
# on purpose (a non-binding tracer pulse is the standard characterization
# experiment).
_TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS = frozenset({lwe_spec, step_elution_spec})


def _round_10sf(v: float) -> float:
    """Round to 10 significant figures, clearing browser-slider float noise."""
    return float(f"{v:.10g}")


def _key_for_value(registry: Mapping[str, Any], value: Any) -> Optional[str]:
    """Reverse-lookup a registry's human label for one of its factory values."""
    return next((k for k, v in registry.items() if v == value), None)


class ConfigurationWidget:
    """Pick a component system, column/binding model, and process template; build a process.

    Standalone by default (REQUIREMENTS.md item #32): with no InstrumentWidget
    bound, this widget already builds a real (bare-column) simulation on its
    own, from `STANDALONE_TEMPLATES`. Binding an `InstrumentWidget` via
    `bind_to_instrument()` is an optional layer on top -- it adds a real
    LC-system flow path (sample loop, tubing, mixer) around the *same*
    column/binding choice, and switches the process-template registry to the
    fuller `INSTRUMENT_TEMPLATES` set. This widget's own column/binding/
    component pickers are the single source of truth either way -- binding an
    Instrument only ever feeds it those choices, never the reverse.

    `.process` holds the latest successfully-built object; `add_listener`
    registers a callback that fires with it on every successful build.
    """

    def __init__(
        self,
        *,
        instrument: Optional[InstrumentWidget] = None,
        registry: Optional[Dict[str, Callable[[Any], Any]]] = None,
        columns: Optional[Dict[str, type]] = None,
        binding_registry: Optional[Dict[str, Optional[type]]] = None,
    ) -> None:
        self._registry_override = registry
        self._columns = columns or COLUMN_MODELS
        self._binding_registry = binding_registry or BINDING_MODELS
        self._column_cache: Dict[Any, Any] = {}
        self._binding_cache: Dict[Any, Any] = {}
        self._instrument: Optional[InstrumentWidget] = None
        self._listeners: List[Callable[[Any], None]] = []
        self.process: Any = None
        self._column_form: Optional[FormRenderer] = None
        self._binding_form: Optional[FormRenderer] = None
        self._model_form: Optional[FormRenderer] = None
        self._event_sliders: Dict[str, W.FloatSlider] = {}
        self._cycle_time_minutes_element: Optional[FloatField] = None
        # Set around _apply_state()'s picker/component writes so each one's
        # own observer doesn't trigger its own full rebuild -- one rebuild for
        # the whole restored selection instead of one per field touched.
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

        # "Components:" row editor in the Component System section -- the
        # single source of truth for component names, whether or not an
        # Instrument is bound (see class docstring).
        self._components = ComponentListField(label="Components:")
        self._component_note = W.HTML(layout=W.Layout(display="none"))
        self._component_note.add_class("cadetgui-note")

        self._column_picker = ChoiceField(
            label="Column Model:", options=self._column_options(),
            value=self._columns.get("Lumped Rate Model Without Pores (LRM)"),
        )
        self._binding_picker = ChoiceField(
            label="Binding Model:", options=list(self._binding_registry.items()),
            value=self._binding_registry.get("Linear"),
        )
        self._model_picker = ChoiceField(
            label="Process Template:", options=list(self._active_registry().items())
        )

        # Empty boxes filled in by _rebuild_forms() with each FormRenderer's
        # rendered fields once a column/binding model/template is available.
        self._column_form_box = W.VBox([])
        self._binding_form_box = W.VBox([])
        self._model_form_box = W.VBox([])
        # Right-hand column of the Process section: the interactive event/
        # flow-rate-over-time chart, redrawn on every slider move.
        self._event_plot_label = W.HTML("<div class='cadetgui-section-title'>Event Timeline</div>")
        self._event_chart = EventTimelineChart()
        # Status line at the very bottom of the panel.
        self.status = W.HTML("<em>Select a column and model.</em>")
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
                self._column_settings.button,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )
        column_section = W.VBox(
            [
                column_header,
                self._column_settings.box,
                self._column_picker,
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
                self._process_settings.button,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )

        model_form_column = W.VBox([self._model_form_box])
        model_form_column.add_class("cadetgui-section-wide")

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

        if instrument is not None:
            self.bind_to_instrument(instrument)
        else:
            self._sync_component_minimum()
            if not self._maybe_autoadd_component():
                self._rebuild_forms()

    def bind_to_instrument(self, instrument: InstrumentWidget) -> None:
        """Attach an optional LC-system topology layer -- see class docstring.

        Feeds this widget's own column/binding/component choices into the
        instrument (never the other way around) and switches to the fuller
        `INSTRUMENT_TEMPLATES` process registry.
        """
        self._instrument = instrument
        instrument.add_listener(self._on_instrument_changed)
        self._column_cache.clear()
        self._binding_cache.clear()

        self._suspend_rebuild = True
        try:
            self._refresh_picker_options()
            instrument.components = list(self._components.value)
            instrument.set_column_and_binding(self._column_picker.value, self._binding_picker.value)
            self._sync_instrument_requirements()
        finally:
            self._suspend_rebuild = False

        self._sync_component_minimum()
        if not self._maybe_autoadd_component():
            self._rebuild_forms()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.process` on every build or name change."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.process)

    def _instrument_active(self) -> bool:
        """Whether an Instrument is bound (its LC topology is then always in effect).

        Unbound, this widget builds its own standalone process instead.
        """
        return self._instrument is not None

    def _column_options(self) -> list[tuple[str, type]]:
        """Return this widget's column options -- CSTR only while no instrument is bound."""
        if not self._instrument_active():
            return list(self._columns.items())
        return [(k, v) for k, v in self._columns.items() if k in INSTRUMENT_COMPATIBLE_COLUMNS]

    def _active_registry(self) -> Dict[str, Callable[[Any], Any]]:
        if self._registry_override is not None:
            return self._registry_override
        return INSTRUMENT_TEMPLATES if self._instrument_active() else STANDALONE_TEMPLATES

    @property
    def _registry(self) -> Dict[str, Callable[[Any], Any]]:
        return self._active_registry()

    def _refresh_picker_options(self) -> None:
        """Re-derive the column and process-template picker options.

        Called on bind and again on every Instrument change --
        `ChoiceField.set_options` falls
        back to the first option when the current value isn't among the new
        ones, so this is safe to call unconditionally.
        """
        self._column_picker.set_options(self._column_options())
        self._model_picker.set_options(list(self._active_registry().items()))

    @property
    def flow_sheet(self) -> Optional[LCFlowSheet]:
        """The bound instrument's current flow sheet, or None if unbound/unbuilt."""
        return self._instrument.flow_sheet if self._instrument is not None else None

    @property
    def components(self) -> List[str]:
        """Current component names."""
        return list(self._components.value)

    @components.setter
    def components(self, names: List[str]) -> None:
        self._components.value = list(names)

    def _get_column(self) -> Any:
        if self._instrument_active():
            flow_sheet = self.flow_sheet
            return getattr(flow_sheet, "column", None) if flow_sheet is not None else None
        column_cls = self._column_picker.value
        if column_cls is None:
            return None
        cache_key = (column_cls, tuple(self._components.value))
        if cache_key not in self._column_cache:
            cs = ComponentSystem(list(self._components.value))
            self._column_cache[cache_key] = column_cls(cs, name="column")
        return self._column_cache[cache_key]

    def _get_binding_model(self) -> Any:
        column = self._get_column()
        if column is None:
            return None
        if self._instrument_active():
            return getattr(column, "binding_model", None)
        binding_cls = self._binding_picker.value
        if binding_cls is None:
            return None
        # Keyed by id(column): a binding model's component_system must be the
        # same object as its column's, and each column gets its own.
        cache_key = (binding_cls, id(column))
        if cache_key not in self._binding_cache:
            self._binding_cache[cache_key] = binding_cls(
                column.component_system, name="binding_model"
            )
        return self._binding_cache[cache_key]

    def _on_instrument_changed(self, flow_sheet: Any) -> None:
        if self._suspend_rebuild:
            return
        if flow_sheet is None:
            self.process = None
            self.persistence.refresh_hash_display()
            self._notify()
            self.status.value = status_html(
                "error", "The System has invalid inputs -- fix them to rebuild the process."
            )
            return
        self._refresh_picker_options()
        self._sync_component_minimum()
        if self._maybe_autoadd_component():
            return  # setting self._components.value already rebuilt the forms
        self._rebuild_forms()

    def _on_components_change(self, change: dict) -> None:
        if change.get("name") != "value":
            return
        self._column_cache.clear()
        self._binding_cache.clear()
        if self._instrument is not None:
            self._instrument.components = list(self._components.value)
        else:
            self._rebuild_forms()

    def _on_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        if self._instrument is not None:
            self._instrument.set_column_and_binding(
                self._column_picker.value, self._binding_picker.value
            )
        else:
            self._column_cache.clear()
            self._binding_cache.clear()
            self._rebuild_forms()

    def _sync_instrument_requirements(self) -> None:
        """Tell a bound instrument which units the selected template can't be built without."""
        if self._instrument is None:
            return
        model_fn = self._model_picker.value
        was_suspended = self._suspend_rebuild
        self._suspend_rebuild = True
        try:
            self._instrument.set_required_units(
                template_required_units(model_fn),
                reason=_key_for_value(self._active_registry(), model_fn) or "",
            )
        finally:
            self._suspend_rebuild = was_suspended

    def _on_model_selection_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._sync_instrument_requirements()
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
        if self._instrument is not None and self._instrument.flow_sheet is None:
            return
        self.process = built
        if self._instrument is not None:
            self._instrument.set_active_inlets(active_inlets(built))
        self.persistence.refresh_hash_display()
        self._notify()
        self.status.value = "<em>Process built.</em>"

    def _snapshot_state(self) -> ConfigurationState:
        """Capture the current selection + field values as the hashed save/import payload."""
        if self._model_form is None:
            raise RuntimeError(
                "Nothing built yet -- pick a column and a process template first."
            )
        column_key = _key_for_value(self._columns, self._column_picker.value)
        binding_key = _key_for_value(self._binding_registry, self._binding_picker.value)
        template_key = _key_for_value(self._active_registry(), self._model_picker.value)
        if column_key is None or binding_key is None or template_key is None:
            raise RuntimeError("Current selection isn't in a known registry -- can't snapshot it.")
        return ConfigurationState(
            components=list(self._components.value),
            column_key=column_key,
            binding_key=binding_key,
            template_key=template_key,
            instrument=self._instrument.snapshot() if self._instrument is not None else None,
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
        """Reconstruct pickers/forms (and a bound instrument, if any) from a saved state."""
        column_cls = self._columns.get(state.column_key)
        binding_cls = self._binding_registry.get(state.binding_key)
        if column_cls is None or binding_cls is None:
            raise ValueError(
                "Saved configuration references a column or binding model"
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
            self._components.value = list(state.components)

            # Restore the Instrument's state before setting the pickers.
            if self._instrument is not None:
                if state.instrument is not None:
                    self._instrument.apply_state(state.instrument)
                self._refresh_picker_options()

            self._column_picker.value = column_cls
            self._binding_picker.value = binding_cls
            if self._instrument is not None:
                self._instrument.components = list(state.components)
                self._instrument.set_column_and_binding(column_cls, binding_cls)

            template_factory = self._active_registry().get(state.template_key)
            if template_factory is None:
                raise ValueError(
                    "Saved configuration references a process template"
                    " that isn't registered here anymore."
                )
            self._model_picker.value = template_factory
            self._sync_instrument_requirements()
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
        # INSTRUMENT_TEMPLATES build against the bound instrument's flow
        # sheet; STANDALONE_TEMPLATES build directly against the bare column.
        model_arg = self.flow_sheet if self._instrument_active() else column
        if model_arg is None or model_fn is None:
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

        self._model_form = FormRenderer(model_fn(model_arg), on_built=self._on_process_built)
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
                layout=W.Layout(width="100%", max_width="200px", min_width="90px"),
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
            units=r"\mathrm{min}",
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
                component_names = list(self._components.value)
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
        Two shapes depending on whether an Instrument is bound: an
        `LCFlowSheet`-based script, or (standalone) a bare
        Inlet -> column -> Outlet script via the template's own `export` hook
        (see `cadetprocessadapter.pulse_feed_spec`).
        """
        if self.process is None or self._model_form is None:
            raise RuntimeError(
                "Nothing built yet — pick a column and a process template first."
            )

        column = self._get_column()
        binding_model = self._get_binding_model()
        cs_cls = ComponentSystem
        proc_cls = type(self.process)
        names = list(self._components.value)

        if self._instrument_active():
            return self._export_instrument_script(column, binding_model, cs_cls, proc_cls, names)
        return self._export_standalone_script(column, binding_model, cs_cls, proc_cls, names)

    def _export_instrument_script(
        self, column: Any, binding_model: Any, cs_cls: type, proc_cls: type, names: List[str]
    ) -> str:
        flow_sheet = self.flow_sheet
        if flow_sheet is None:
            raise RuntimeError(
                "Nothing built yet — the bound Instrument hasn't built a flow sheet."
            )
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
            "",
            f"component_system = {cs_cls.__name__}({names!r})",
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

        return "\n".join(imports + lines)

    def _export_standalone_script(
        self, column: Any, binding_model: Any, cs_cls: type, proc_cls: type, names: List[str]
    ) -> str:
        if column is None:
            raise RuntimeError("Nothing built yet — pick a column model first.")
        export_fn = self._model_form.spec.export
        if export_fn is None:
            raise RuntimeError(f"{self._model_form.spec.title!r} has no export support.")

        col_cls = type(column)
        imports = [
            f"from {cs_cls.__module__} import {cs_cls.__name__}",
            "from CADETProcess.processModel import FlowSheet, Inlet, Outlet",
            f"from {col_cls.__module__} import {col_cls.__name__}",
        ]
        if binding_model is not None:
            bind_cls = type(binding_model)
            imports.append(f"from {bind_cls.__module__} import {bind_cls.__name__}")
        imports.append(f"from {proc_cls.__module__} import {proc_cls.__name__}")

        lines = [
            "",
            f"component_system = {cs_cls.__name__}({names!r})",
            "",
            f"column = {col_cls.__name__}(component_system, name='column')",
        ]
        for name, value in self._column_form.collect_values().items():
            lines.append(f"column.{name} = {value!r}")

        if binding_model is not None:
            bind_cls = type(binding_model)
            lines.append(
                f"column.binding_model = {bind_cls.__name__}("
                "component_system, name='binding_model')"
            )
            for name, value in self._binding_form.collect_values().items():
                lines.append(f"column.binding_model.{name} = {value!r}")

        lines.extend(export_fn(self._model_form.collect_values()))
        return "\n".join(imports + lines)

    def _on_export(self, _btn: Any) -> None:
        try:
            script = self.export_script()
        except RuntimeError as exc:
            self.status.value = status_html("error", str(exc))
            return
        self._script_out.value = script
        self._script_out.layout.display = ""
        self.status.value = "<em>Script generated below.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
