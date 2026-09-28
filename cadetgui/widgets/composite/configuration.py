from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    BINDING_MODELS,
    COLUMN_MODELS,
    INSTRUMENT_COMPATIBLE_COLUMNS,
    INSTRUMENT_TEMPLATES,
    MULTIPLEXABLE_COLUMN_PARAMS,
    STANDALONE_TEMPLATES,
    active_inlets,
    build_parameter_config_spec,
    equilibration_inlets,
    inlet_contents,
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
from ._script_export import instrument_script, standalone_script
from ._timeline_data import timeline_chart_data
from .configuration_persistence import ConfigurationPersistence
from .instrument import InstrumentWidget
from .workspace_header import WorkspaceHeader

__all__ = ["ConfigurationWidget"]

_CYCLE_TIME_SLIDER_MAX_SECONDS = 300.0 * 60.0
_DEFAULT_CONFIG_NAME = "New Experiment"
_BYPASS_NOTE = "Column is bypassed in the System configuration -- these settings are not used."

# Gradient templates are meaningless with a single component.
_TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS = frozenset({lwe_spec, step_elution_spec})


def _round_10sf(v: float) -> float:
    """Round to 10 significant figures, clearing browser-slider float noise."""
    return float(f"{v:.10g}")


def _key_for_value(registry: Mapping[str, Any], value: Any) -> Optional[str]:
    """Reverse-lookup a registry's human label for one of its factory values."""
    return next((k for k, v in registry.items() if v == value), None)


def _checkbox(description: str, on_change: Callable[[dict], None]) -> W.Checkbox:
    checkbox = W.Checkbox(description=description, value=False, indent=False)
    checkbox.observe(on_change, names="value")
    return checkbox


def _note(text: str = "") -> W.HTML:
    note = W.HTML(text, layout=W.Layout(display="none"))
    note.add_class("cadetgui-note")
    return note


def _section(children: list, *classes: str) -> W.VBox:
    box = W.VBox(children)
    for cls in ("cadetgui-section", *classes):
        box.add_class(cls)
    return box


def _titled_header(title: str, settings: SettingsPopover) -> W.HBox:
    return W.HBox(
        [W.HTML(f"<div class='cadetgui-section-title'>{title}</div>"), settings.button],
        layout=W.Layout(justify_content="space-between", align_items="center"),
    )


class ConfigurationWidget:
    """Pick a component system, column/binding model, and process template; build a process.

    Standalone by default: with no `InstrumentWidget` bound, it builds a bare-column
    simulation from `STANDALONE_TEMPLATES`. `bind_to_instrument()` adds a real LC-system
    flow path around the same column/binding choice and switches to `INSTRUMENT_TEMPLATES`.
    This widget's pickers stay the single source of truth either way.

    `.process` holds the latest successfully-built object; `add_listener` registers a
    callback that fires with it on every successful build.

    `.workspace_header` (name, Save, saved-version/run counts, backend versions) is embedded
    at the top of this panel by default; pass `workspace_header=False` when a shell places
    `workspace_header.root` elsewhere.
    """

    def __init__(
        self,
        *,
        instrument: Optional[InstrumentWidget] = None,
        workspace_header: bool = True,
    ) -> None:
        self._column_cache: dict[Any, Any] = {}
        self._binding_cache: dict[Any, Any] = {}
        self._instrument: Optional[InstrumentWidget] = None
        self._listeners: List[Callable[[Any], None]] = []
        self.process: Any = None
        self._column_form: Optional[FormRenderer] = None
        self._binding_form: Optional[FormRenderer] = None
        self._forms_key: Optional[tuple] = None
        self._model_form: Optional[FormRenderer] = None
        self._event_sliders: dict[str, W.FloatSlider] = {}
        self._cycle_time_minutes_element: Optional[FloatField] = None
        # Set around _apply_state()'s writes so the restored selection rebuilds once.
        self._suspend_rebuild = False

        self._multiplex_state: dict[str, bool] = dict.fromkeys(MULTIPLEXABLE_COLUMN_PARAMS, False)
        self._multiplex_checkboxes: dict[str, W.Checkbox] = {
            name: _checkbox(
                f"Enable {name.replace('_', ' ').title()} Multiplex",
                self._make_on_multiplex_change(name),
            )
            for name in MULTIPLEXABLE_COLUMN_PARAMS
        }
        self._show_optional_column_checkbox = _checkbox(
            "Show optional parameters", self._on_show_optional_change
        )
        self._column_settings = SettingsPopover(
            tooltip="Column settings",
            children=[self._show_optional_column_checkbox, *self._multiplex_checkboxes.values()],
        )

        self._show_optional_binding_checkbox = _checkbox(
            "Show optional parameters", self._on_show_optional_change
        )
        self._binding_settings = SettingsPopover(
            tooltip="Binding settings", children=[self._show_optional_binding_checkbox]
        )

        self._cycle_time_unit_checkbox = _checkbox(
            "Show Cycle Time in Minutes", self._on_cycle_time_unit_change
        )
        self._process_settings = SettingsPopover(
            tooltip="Process display settings",
            children=[self._cycle_time_unit_checkbox],
            visible=False,
        )

        self._components = ComponentListField(label="Components:")
        self._component_note = _note()
        self._column_bypass_note = _note(_BYPASS_NOTE)
        self._binding_bypass_note = _note(_BYPASS_NOTE)

        self._column_picker = ChoiceField(
            label="Column Model:",
            options=self._column_options(),
            value=COLUMN_MODELS.get("Lumped Rate Model Without Pores (LRM)"),
        )
        self._binding_picker = ChoiceField(
            label="Binding Model:",
            options=list(BINDING_MODELS.items()),
            value=BINDING_MODELS.get("Linear"),
        )
        self._model_picker = ChoiceField(
            label="Process Template:", options=list(self._active_registry().items())
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

        self.persistence = ConfigurationPersistence(
            default_name=_DEFAULT_CONFIG_NAME,
            snapshot=self._snapshot_state,
            apply_state=self._apply_state,
            get_process=lambda: self.process,
            on_name_change=lambda _name: self._notify(),
        )
        self.workspace_header = WorkspaceHeader(self.persistence)
        self.workspace_header_embedded = workspace_header

        components_section = _section(
            [
                W.HTML("<div class='cadetgui-section-title'>Component System</div>"),
                self._components,
                self._component_note,
            ]
        )
        column_section = _section(
            [
                _titled_header("Column Model", self._column_settings),
                self._column_settings.box,
                self._column_bypass_note,
                self._column_picker,
                self._column_form_box,
            ],
            "cadetgui-section-half",
        )
        binding_section = _section(
            [
                _titled_header("Binding Model", self._binding_settings),
                self._binding_settings.box,
                self._binding_bypass_note,
                self._binding_picker,
                self._binding_form_box,
            ],
            "cadetgui-section-half",
        )
        column_binding_row = W.HBox([column_section, binding_section])
        column_binding_row.add_class("cadetgui-row")

        model_form_column = W.VBox([self._model_form_box])
        model_form_column.add_class("cadetgui-section-wide")
        event_chart_column = W.VBox([self._event_plot_label, self._event_chart])
        event_chart_column.add_class("cadetgui-section-half")
        process_columns = W.HBox([model_form_column, event_chart_column])
        process_columns.add_class("cadetgui-row")
        process_section = _section(
            [
                _titled_header("Process", self._process_settings),
                self._process_settings.box,
                self._model_picker,
                process_columns,
            ]
        )

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                *([self.workspace_header.root] if workspace_header else []),
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
            self._apply_template_constraints()

    def bind_to_instrument(self, instrument: InstrumentWidget) -> None:
        """Attach the LC-system topology layer and switch to the `INSTRUMENT_TEMPLATES` registry."""
        self._instrument = instrument
        instrument.add_listener(self._on_instrument_changed)
        self._column_cache.clear()
        self._binding_cache.clear()

        self._suspend_rebuild = True
        try:
            self._refresh_picker_options()
            instrument.components = list(self._components.value)
            self._push_column_to_instrument()
            self._sync_instrument_requirements()
        finally:
            self._suspend_rebuild = False
        self._apply_template_constraints()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.process` on every build or name change."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.process)

    def _column_options(self) -> list[tuple[str, type]]:
        if self._instrument is None:
            return list(COLUMN_MODELS.items())
        return [(k, v) for k, v in COLUMN_MODELS.items() if k in INSTRUMENT_COMPATIBLE_COLUMNS]

    def _active_registry(self) -> dict[str, Callable[[Any], Any]]:
        return STANDALONE_TEMPLATES if self._instrument is None else INSTRUMENT_TEMPLATES

    def _refresh_picker_options(self) -> None:
        """Re-derive column and template options; `set_options` keeps a still-valid value."""
        self._column_picker.set_options(self._column_options())
        self._model_picker.set_options(list(self._active_registry().items()))
        self._sync_template_dropdown()

    def _push_column_to_instrument(self) -> None:
        self._instrument.set_column_and_binding(
            self._column_picker.value,
            self._binding_picker.value,
            _key_for_value(COLUMN_MODELS, self._column_picker.value),
        )

    def _sync_template_dropdown(self) -> None:
        if self._instrument is None:
            return
        registry = self._active_registry()
        self._instrument.set_template_options(
            list(registry), _key_for_value(registry, self._model_picker.value),
            self._select_template,
        )

    def _select_template(self, label: str) -> None:
        template = self._active_registry().get(label)
        if template is not None:
            self._model_picker.value = template

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

    @property
    def column_form(self) -> Optional[FormRenderer]:
        """The column parameter form, or None while no column is available."""
        return self._column_form

    @property
    def binding_form(self) -> Optional[FormRenderer]:
        """The binding-model parameter form, or None while no binding model is available."""
        return self._binding_form

    def _get_column(self) -> Any:
        if self._instrument is not None:
            flow_sheet = self.flow_sheet
            return getattr(flow_sheet, "column", None) if flow_sheet is not None else None
        return self._cached_column()

    def _cached_column(self) -> Any:
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
        if self._instrument is not None:
            return getattr(column, "binding_model", None)
        return self._cached_binding_model(column)

    def _cached_binding_model(self, column: Any) -> Any:
        binding_cls = self._binding_picker.value
        if binding_cls is None:
            return None
        # A binding model must share its column's component system, so it is keyed per column.
        cache_key = (binding_cls, id(column))
        if cache_key not in self._binding_cache:
            self._binding_cache[cache_key] = binding_cls(
                column.component_system, name="binding_model"
            )
        return self._binding_cache[cache_key]

    def _column_bypassed(self) -> bool:
        return self._instrument is not None and "column" in self._instrument.bypass_units()

    def _form_key(self) -> tuple:
        """Everything that fixes the shape of the column/binding forms."""
        return (
            self._column_picker.value,
            self._binding_picker.value,
            tuple(self._components.value),
            tuple(sorted(self._multiplex_state.items())),
            bool(self._show_optional_column_checkbox.value),
            bool(self._show_optional_binding_checkbox.value),
        )

    def _sync_column_bypass(self) -> None:
        """Grey out the column and binding model controls while the column is bypassed."""
        off = self._column_bypassed()
        for control in (
            self._column_picker,
            self._binding_picker,
            self._show_optional_column_checkbox,
            self._show_optional_binding_checkbox,
            *self._multiplex_checkboxes.values(),
        ):
            control.disabled = off
        for form in (self._column_form, self._binding_form):
            if form is not None:
                form.set_disabled(off)
        display = "" if off else "none"
        self._column_bypass_note.layout.display = display
        self._binding_bypass_note.layout.display = display

    def _on_instrument_changed(self, flow_sheet: Any) -> None:
        if self._suspend_rebuild:
            return
        if flow_sheet is None:
            self.process = None
            self._sync_column_bypass()
            self.persistence.refresh_hash_display()
            self._notify()
            self.status.value = status_html(
                "error", "The System has invalid inputs -- fix them to rebuild the process."
            )
            return
        self._refresh_picker_options()
        self._apply_template_constraints()

    def _on_components_change(self, _change: dict) -> None:
        self._column_cache.clear()
        self._binding_cache.clear()
        if self._instrument is not None:
            self._instrument.components = list(self._components.value)
        else:
            self._rebuild_forms()

    def _on_selection_change(self, _change: dict) -> None:
        if self._instrument is not None:
            self._push_column_to_instrument()
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

    def _on_model_selection_change(self, _change: dict) -> None:
        if self._instrument is not None:
            self._instrument.select_template(
                _key_for_value(self._active_registry(), self._model_picker.value)
            )
        self._sync_instrument_requirements()
        self._apply_template_constraints()

    def _required_min_components(self) -> int:
        return 2 if self._model_picker.value in _TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS else 1

    def _apply_template_constraints(self) -> None:
        """Enforce the template's component floor, then rebuild the forms."""
        required = self._required_min_components()
        self._components.min_components = required
        if required > 1:
            self._component_note.value = (
                f"The process template you selected does not allow less than {required} components."
            )
            self._component_note.layout.display = ""
        else:
            self._component_note.layout.display = "none"

        names = self._components.value
        if len(names) < required:
            # Setting the components rebuilds the forms through `_on_components_change`.
            self._components.value = [
                *names,
                *(f"Component {i}" for i in range(len(names) + 1, required + 1)),
            ]
        else:
            self._rebuild_forms()

    def _make_on_multiplex_change(self, name: str) -> Callable[[dict], None]:
        def _on_change(change: dict) -> None:
            self._multiplex_state[name] = bool(change["new"])
            self._rebuild_forms()

        return _on_change

    def _on_show_optional_change(self, _change: dict) -> None:
        self._rebuild_forms()

    def _on_process_built(self, built: Any) -> None:
        if self._instrument is not None and self._instrument.flow_sheet is None:
            return
        self.process = built
        if self._instrument is not None:
            self._instrument.set_active_inlets(
                active_inlets(built), inlet_contents(built), equilibration_inlets(built)
            )
        self.persistence.refresh_hash_display()
        self._notify()
        self.status.value = "<em>Process built.</em>"

    def _snapshot_state(self) -> ConfigurationState:
        """Capture the current selection and field values as the hashed save/import payload."""
        if self._model_form is None:
            raise RuntimeError("Nothing built yet -- pick a column and a process template first.")
        column_key = _key_for_value(COLUMN_MODELS, self._column_picker.value)
        binding_key = _key_for_value(BINDING_MODELS, self._binding_picker.value)
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
        """Snapshot and save the current configuration to the store; return its path."""
        return self.persistence.persist_to_store()

    def import_from_store(self, hash_: str) -> None:
        """Load a configuration previously saved to the local store, by its hash."""
        self.persistence.import_from_store(hash_)

    def _apply_state(self, name: str, state: ConfigurationState) -> None:
        """Reconstruct pickers/forms (and a bound instrument, if any) from a saved state."""
        column_cls = COLUMN_MODELS.get(state.column_key)
        binding_cls = BINDING_MODELS.get(state.binding_key)
        if column_cls is None or binding_cls is None:
            raise ValueError(
                "Saved configuration references a column or binding model"
                " that isn't registered here anymore."
            )
        template_factory = self._active_registry().get(state.template_key)
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
            self._components.value = list(state.components)

            if self._instrument is not None:
                if state.instrument is not None:
                    self._instrument.apply_state(state.instrument)
                self._refresh_picker_options()

            self._column_picker.value = column_cls
            self._binding_picker.value = binding_cls
            if self._instrument is not None:
                self._instrument.components = list(state.components)
                self._push_column_to_instrument()

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
        # A bypassed column has no instance in the flow sheet, so its forms are built
        # against a detached one that keeps the values while it is off.
        if self._column_bypassed():
            column = self._cached_column()
            binding_model = self._cached_binding_model(column) if column is not None else None
        else:
            column = self._get_column()
            binding_model = self._get_binding_model()
        model_fn = self._model_picker.value
        model_arg = self.flow_sheet if self._instrument is not None else column
        if model_arg is None or model_fn is None:
            self._column_form_box.children = ()
            self._binding_form_box.children = ()
            self._model_form_box.children = ()
            self._clear_event_section()
            self._sync_column_bypass()
            self.persistence.refresh_hash_display()
            return

        # A bound instrument hands out a fresh column on every rebuild, so carry the
        # previous forms' values over when their shape is unchanged.
        form_key = self._form_key()
        carry = self._instrument is not None and form_key == self._forms_key
        previous_column = (
            self._column_form.collect_values() if carry and self._column_form else None
        )
        previous_binding = (
            self._binding_form.collect_values() if carry and self._binding_form else None
        )
        self._forms_key = form_key

        self._rebuild_column_form(column, previous_column)
        self._rebuild_binding_form(column, binding_model, previous_binding)
        self._sync_column_bypass()

        self._model_form = FormRenderer(model_fn(model_arg), on_built=self._on_process_built)
        self._model_form_box.children = (self._model_form.root,)
        self._rebuild_event_sliders()
        # The model form's `on_built` fires inside its constructor, before `_model_form` is
        # assigned, so the hash must be refreshed again here.
        self.persistence.refresh_hash_display()

        self.status.value = (
            "<em>Fields apply automatically as you edit them"
            " (column and binding model first, since the process picks up"
            " whatever's currently set on them).</em>"
        )

    def _rebuild_column_form(self, column: Any, previous: Optional[dict]) -> None:
        if column is None:
            self._column_form = None
            self._column_form_box.children = ()
            return
        applicable = set(getattr(column, "required_parameters", None) or []) & (
            MULTIPLEXABLE_COLUMN_PARAMS
        )
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
        if previous is not None:
            self._column_form.set_values(previous)

    def _rebuild_binding_form(
        self, column: Any, binding_model: Any, previous: Optional[dict]
    ) -> None:
        if binding_model is None:
            self._binding_form = None
            self._binding_form_box.children = ()
            return

        def _attach_binding(built: Any) -> None:
            column.binding_model = built

        self._binding_form = FormRenderer(
            build_parameter_config_spec(
                binding_model, include_optional=self._show_optional_binding_checkbox.value
            ),
            on_built=_attach_binding,
        )
        self._binding_form_box.children = (self._binding_form.root,)
        if previous is not None:
            self._binding_form.set_values(previous)

    def _clear_event_section(self) -> None:
        self._event_sliders = {}
        self._cycle_time_minutes_element = None
        self._clear_event_chart()

    def _clear_event_chart(self) -> None:
        self._event_chart.series = []
        self._event_chart.phases = []
        self._event_chart.markers = []

    def _rebuild_event_sliders(self) -> None:
        """Link a slider to each scalar float field; a slider move commits like typing does."""
        self._event_sliders = {}
        self._cycle_time_minutes_element = None
        fields = self._model_form.spec.fields
        self._process_settings.visible = any(f.name == "cycle_time" for f in fields)

        for f in fields:
            if f.kind != "float":
                continue
            el = self._model_form.element(f.name)
            default = float(el.value)
            if f.name == "cycle_time":
                slider_max = max(default, _CYCLE_TIME_SLIDER_MAX_SECONDS)
            else:
                slider_max = default * 5 if default > 0 else 1.0
            # The default must sit on the step grid, or the browser snaps it and reports it back.
            step = default / 100 if default > 0 else 0.01
            slider = W.FloatSlider(
                value=default,
                min=0.0,
                max=slider_max,
                step=step,
                readout=False,
                layout=W.Layout(width="100%", max_width="200px", min_width="90px"),
            )
            # dlink + rounding rather than link: slider drags report float noise.
            W.dlink((slider, "value"), (el, "value"), transform=_round_10sf)
            W.dlink((el, "value"), (slider, "value"), transform=_round_10sf)
            slider.observe(lambda _change: self._redraw_event_plot(), names="value")
            self._event_sliders[f.name] = slider

        name_of = {id(self._model_form.element(f.name)): f.name for f in fields}
        children = []
        for child in self._model_form.root.children:
            name = name_of.get(id(child))
            extras = []
            if name == "cycle_time":
                extras.append(self._make_cycle_time_unit_toggle(child))
            if name in self._event_sliders:
                extras.append(self._event_sliders[name])
            if extras:
                # Wrap rather than overlap the slider on a narrow window.
                children.append(
                    W.HBox(
                        [child, *extras],
                        layout=W.Layout(flex_flow="row wrap", align_items="center"),
                    )
                )
            else:
                children.append(child)
        self._model_form.root.children = tuple(children)

        self._event_plot_label.layout.display = "" if self._event_sliders else "none"
        self._redraw_event_plot()

    def _make_cycle_time_unit_toggle(self, seconds_element: Any) -> Any:
        """Return a minutes companion of the cycle-time field, kept in sync in both directions."""
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

    def _on_cycle_time_unit_change(self, _change: dict) -> None:
        self._apply_cycle_time_unit_display()

    def _apply_cycle_time_unit_display(self) -> None:
        if self._cycle_time_minutes_element is None or self._model_form is None:
            return
        seconds_element = self._model_form.element("cycle_time")
        show_minutes = self._cycle_time_unit_checkbox.value
        seconds_element.layout.display = "none" if show_minutes else ""
        self._cycle_time_minutes_element.layout.display = "" if show_minutes else "none"

    def _redraw_event_plot(self) -> None:
        """Redraw the chart from the form's already-committed build, if there is one."""
        if self._model_form is None or self._model_form.built is None:
            return
        data = timeline_chart_data(
            self._model_form.built, self._components.value, self._model_form.spec.phase_names
        )
        if data is None:
            self._clear_event_chart()
            return
        chart = self._event_chart
        chart.y_label = data["y_label"]
        chart.phases = data["phases"]
        chart.markers = data["markers"]
        chart.series = data["series"]

    def export_script(self) -> str:
        """Generate an executable CADET-Process script that rebuilds the current process."""
        if self.process is None or self._model_form is None:
            raise RuntimeError("Nothing built yet — pick a column and a process template first.")
        column = self._get_column()
        binding_model = self._get_binding_model()
        common = {
            "process": self.process,
            "column": column,
            "binding_model": binding_model,
            "component_names": list(self._components.value),
            "column_values": self._column_form.collect_values() if self._column_form else {},
            "binding_values": self._binding_form.collect_values() if self._binding_form else {},
            "model_values": self._model_form.collect_values(),
        }
        if self._instrument is not None:
            flow_sheet = self.flow_sheet
            if flow_sheet is None:
                raise RuntimeError(
                    "Nothing built yet — the bound Instrument hasn't built a flow sheet."
                )
            return instrument_script(
                flow_sheet=flow_sheet, state=self._instrument.snapshot(), **common
            )
        if column is None:
            raise RuntimeError("Nothing built yet — pick a column model first.")
        export = self._model_form.spec.export
        if export is None:
            raise RuntimeError(f"{self._model_form.spec.title!r} has no export support.")
        return standalone_script(export=export, **common)

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
