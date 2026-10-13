from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet

from ...instrument.starting_values import with_starting_values
from ...instrument.system import (
    BINDING_MODELS,
    COLUMN_MODELS,
    INSTRUMENT_COMPATIBLE_COLUMNS,
    active_inlets,
    equilibration_inlets,
    inlet_contents,
)
from ...instrument.templates import (
    INSTRUMENT_TEMPLATES,
    STANDALONE_TEMPLATES,
    lwe_spec,
    step_elution_spec,
    template_required_units,
)
from ...io.configuration_store import ConfigurationState
from ...parameters.specs import parameter_defaults
from ..base import Widget
from ..benches.frame import WorkspaceHeader
from ..elements import ComponentListField
from ..forms import FormRenderer
from ..ui.html import status_html
from ..ui.layout import note, section
from ..ui.theme import style_tag
from .column_binding import ColumnBindingSection
from .flow_rate import FlowRateSection
from .instrument import InstrumentWidget
from .persistence import ConfigurationPersistence
from .process_section import ProcessSection
from .script_export import instrument_script, standalone_script

__all__ = [
    "ConfigurationWidget",
    "FlowRateSection",
]


_DEFAULT_CONFIG_NAME = "New Project"


# Gradient templates are meaningless with a single component.
_TEMPLATES_REQUIRING_MULTIPLE_COMPONENTS = frozenset({lwe_spec, step_elution_spec})


def _key_for_value(registry: Mapping[str, Any], value: Any) -> Optional[str]:
    """Reverse-lookup a registry's human label for one of its factory values."""
    return next((k for k, v in registry.items() if v == value), None)


def _part(holder: str, name: str) -> property:
    """Expose attribute `name` of the helper object stored at `holder`."""
    return property(
        lambda self: getattr(getattr(self, holder), name),
        lambda self, value: setattr(getattr(self, holder), name, value),
    )


class ConfigurationWidget(Widget):
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

    Bound to an instrument, the component names are edited in the instrument's Components
    section; this widget's own "Component System" section is hidden and follows it.

    `show_process_template=False` hides the process-template picker and the template's
    method fields; the template stays selected internally so `snapshot()` still
    returns a complete recipe, and a bound instrument's sample loop is not locked by it.
    `intro` is HTML shown under the panel title. `set_flow_rate()` sets the flow rate every
    snapshot carries, whatever the method form holds.

    `starting_values` (also a checkbox, `use_starting_values`) fills the standard starting
    values (`cadetgui.instrument.starting_values`) into freshly chosen models; off, forms keep the
    CADET-Process and template defaults.
    """

    _column_picker = _part("_models", "column_picker")
    _binding_picker = _part("_models", "binding_picker")
    _column_form = _part("_models", "column_form")
    _binding_form = _part("_models", "binding_form")
    _column_form_box = _part("_models", "column_form_box")
    _column_bypass_note = _part("_models", "column_bypass_note")
    _binding_bypass_note = _part("_models", "binding_bypass_note")
    _multiplex_checkboxes = _part("_models", "multiplex_checkboxes")
    _show_optional_column_checkbox = _part("_models", "show_optional_column")
    _show_optional_binding_checkbox = _part("_models", "show_optional_binding")
    _model_picker = _part("_process", "picker")
    _model_form = _part("_process", "form")
    _model_form_box = _part("_process", "form_box")
    _process_section = _part("_process", "root")
    _process_settings = _part("_process", "settings")
    _event_chart = _part("_process", "chart")
    _event_sliders = _part("_process", "event_sliders")
    _cycle_time_unit_checkbox = _part("_process", "cycle_time_unit_checkbox")
    _cycle_time_minutes_element = _part("_process", "cycle_time_minutes_element")

    def __init__(
        self,
        *,
        instrument: Optional[InstrumentWidget] = None,
        workspace_header: bool = True,
        show_process_template: bool = True,
        intro: str = "",
        starting_values: bool = True,
    ) -> None:
        super().__init__()
        self.show_process_template = show_process_template
        self._starting_values_checkbox = W.Checkbox(
            value=starting_values,
            description="Use standard starting values",
            indent=False,
            tooltip=(
                "Fill binding values, method concentrations and the equilibrated column"
                " start from parameters/starting_values.json when a model is chosen."
            ),
        )
        self._flow_rate: Optional[float] = None
        self._instrument: Optional[InstrumentWidget] = None
        self.process: Any = None
        self._model_key: Optional[tuple] = None
        self._restoring = False
        # Set around _apply_state()'s writes so the restored selection rebuilds once.
        self._suspend_rebuild = False

        self._components = ComponentListField(label="Components:")
        self._component_note = note(hidden=True)
        self._models = ColumnBindingSection(
            on_selection_change=self._on_selection_change,
            on_settings_change=self._rebuild_forms,
            on_reset=self._reset_form,
        )
        self._process = ProcessSection(
            options=list(self._active_registry().items()),
            components=lambda: self._components.value,
        )
        self.status = W.HTML("<em>Select a column and model.</em>")
        self.status.add_class("cadetgui-status")

        self._btn_export = W.Button(description="Export script", icon="code")
        self._script_out = W.Textarea(layout=W.Layout(width="100%", height="220px", display="none"))
        self._script_out.add_class("cadetgui-script")

        self.persistence = ConfigurationPersistence(
            default_name=_DEFAULT_CONFIG_NAME,
            snapshot=self.snapshot,
            apply_state=self._apply_state,
            get_process=lambda: self.process,
            on_name_change=lambda _name: self._notify(self.process),
        )
        self.workspace_header = WorkspaceHeader(self.persistence)
        self.workspace_header_embedded = workspace_header

        self._components_section = section(
            [
                W.HTML("<div class='cadetgui-section-title'>Component System</div>"),
                self._components,
                self._component_note,
            ]
        )
        self._pulling_components = False
        if not show_process_template:
            self._process.root.layout.display = "none"
        intro_html = W.HTML(intro)
        intro_html.add_class("cadetgui-note")
        intro_html.layout.display = "" if intro else "none"

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Configuration</div>"),
                intro_html,
                *([self.workspace_header.root] if workspace_header else []),
                self._starting_values_checkbox,
                self._components_section,
                self._models.root,
                self._process.root,
                self._btn_export,
                self._script_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._components.observe(self._on_components_change, names="value")
        self._model_picker.observe(self._on_model_selection_change, names="selected_index")
        self._btn_export.on_click(self._on_export)
        self._starting_values_checkbox.observe(self._on_starting_values_toggle, names="value")

        if instrument is not None:
            self.bind_to_instrument(instrument)
        else:
            self._apply_template_constraints()

    def bind_to_instrument(self, instrument: InstrumentWidget) -> None:
        """Attach the LC-system topology layer and switch to the `INSTRUMENT_TEMPLATES` registry."""
        self._instrument = instrument
        self._components_section.layout.display = "none"
        instrument.add_listener(self._on_instrument_changed)
        self._models.clear_cache()

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
        super().add_listener(fn)

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
        if self._instrument is None or not self.show_process_template:
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

    def select_models(
        self,
        *,
        template: Optional[str] = None,
        column: Optional[str] = None,
        binding: Optional[str] = None,
    ) -> None:
        """Pick the process template, column and binding model by their registry keys."""
        if template is not None:
            self._model_picker.value = self._active_registry()[template]
        if column is not None:
            self._column_picker.value = COLUMN_MODELS[column]
        if binding is not None:
            self._binding_picker.value = BINDING_MODELS[binding]

    @property
    def use_starting_values(self) -> bool:
        """Whether freshly chosen models get the standard starting values."""
        return bool(self._starting_values_checkbox.value)

    @use_starting_values.setter
    def use_starting_values(self, value: bool) -> None:
        self._starting_values_checkbox.value = bool(value)

    def _on_starting_values_toggle(self, change: dict) -> None:
        if change["new"] and self._model_form is not None:
            self._apply_starting_values(method=True)

    @property
    def flow_rate(self) -> Optional[float]:
        """The flow rate (m³/s) snapshots carry: the one set, else the method form's."""
        if self._flow_rate is not None:
            return self._flow_rate
        if self._model_form is None:
            return None
        values = self._model_form.collect_values()
        value = values.get("flow_rate", values.get("flow_rate_wash"))
        return float(value) if value is not None else None

    def set_flow_rate(self, value: Optional[float]) -> None:
        """Make every snapshot carry flow rate `value` (m³/s); `None` uses the method form."""
        self._flow_rate = None if value is None else float(value)
        self.persistence.refresh_hash_display()
        self._notify(self.process)

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
        return self._models.detached_column(self._components.value)

    def _get_binding_model(self) -> Any:
        column = self._get_column()
        if column is None:
            return None
        if self._instrument is not None:
            return getattr(column, "binding_model", None)
        return self._models.detached_binding_model(column)

    def _column_bypassed(self) -> bool:
        return self._instrument is not None and "column" in self._instrument.bypass_units()

    def _sync_column_bypass(self) -> None:
        self._models.set_bypassed(self._column_bypassed())

    def _on_instrument_changed(self, flow_sheet: Any) -> None:
        if self._suspend_rebuild:
            return
        names = self._instrument.components
        if names != list(self._components.value):
            self._models.clear_cache()
            self._pulling_components = True
            try:
                self._components.value = names
            finally:
                self._pulling_components = False
        if flow_sheet is None:
            self.process = None
            self._sync_column_bypass()
            self.persistence.refresh_hash_display()
            self._notify(self.process)
            self.status.value = status_html(
                "error", "The System has invalid inputs -- fix them to rebuild the process."
            )
            return
        self._refresh_picker_options()
        self._apply_template_constraints()

    def _on_components_change(self, _change: dict) -> None:
        if self._pulling_components:
            return
        self._models.clear_cache()
        if self._instrument is not None:
            self._instrument.components = list(self._components.value)
        else:
            self._rebuild_forms()

    def _on_selection_change(self) -> None:
        if self._instrument is not None:
            self._push_column_to_instrument()
        else:
            self._models.clear_cache()
            self._rebuild_forms()

    def _sync_instrument_requirements(self) -> None:
        """Tell a bound instrument which units the selected template can't be built without."""
        if self._instrument is None or not self.show_process_template:
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
        note = (
            f"The process template you selected does not allow less than {required} components."
            if required > 1 else ""
        )
        self._component_note.value = note
        self._component_note.layout.display = "" if note else "none"
        if self._instrument is not None:
            self._instrument.set_min_components(required, note)

        names = self._components.value
        if len(names) < required:
            # Setting the components rebuilds the forms through `_on_components_change`.
            self._components.value = [
                *names,
                *(f"Component {i}" for i in range(len(names) + 1, required + 1)),
            ]
        else:
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
        self._notify(self.process)
        self.status.value = "<em>Process built.</em>"

    def snapshot(self) -> ConfigurationState:
        """Capture the current selection and field values as the hashed save/import payload."""
        if self._model_form is None:
            raise RuntimeError("Nothing built yet -- pick a column and a process template first.")
        column_key = _key_for_value(COLUMN_MODELS, self._column_picker.value)
        binding_key = _key_for_value(BINDING_MODELS, self._binding_picker.value)
        template_key = _key_for_value(self._active_registry(), self._model_picker.value)
        if column_key is None or binding_key is None or template_key is None:
            raise RuntimeError("Current selection isn't in a known registry -- can't snapshot it.")
        model_values = self._model_form.collect_values()
        if self._flow_rate is not None:
            keys = [k for k in ("flow_rate", "flow_rate_wash") if k in model_values]
            for key in keys or ["flow_rate"]:
                model_values[key] = self._flow_rate
        return ConfigurationState(
            components=list(self._components.value),
            column_key=column_key,
            binding_key=binding_key,
            template_key=template_key,
            instrument=self._instrument.snapshot() if self._instrument is not None else None,
            multiplex_state=dict(self._models.multiplex_state),
            show_optional_column=bool(self._show_optional_column_checkbox.value),
            show_optional_binding=bool(self._show_optional_binding_checkbox.value),
            column_values=self._column_form.collect_values() if self._column_form else {},
            binding_values=self._binding_form.collect_values() if self._binding_form else {},
            model_values=model_values,
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
        self._restoring = True
        try:
            self._restore_state(name, state)
        finally:
            self._restoring = False

    def _restore_state(self, name: str, state: ConfigurationState) -> None:
        column_cls = COLUMN_MODELS.get(state.column_key)
        binding_cls = BINDING_MODELS.get(state.binding_key)
        if column_cls is None or state.binding_key not in BINDING_MODELS:
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
            self._models.restore_settings(
                state.multiplex_state, state.show_optional_column, state.show_optional_binding
            )
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

    def _form_objects(self) -> tuple[Any, Any]:
        """Return the column and binding model the parameter forms edit."""
        # A bypassed column has no instance in the flow sheet, so its forms are built
        # against a detached one that keeps the values while it is off.
        if self._column_bypassed():
            column = self._models.detached_column(self._components.value)
            binding = self._models.detached_binding_model(column) if column is not None else None
            return column, binding
        return self._get_column(), self._get_binding_model()

    def _rebuild_forms(self) -> None:
        if self._suspend_rebuild:
            return
        column, binding_model = self._form_objects()
        model_fn = self._model_picker.value
        model_arg = self.flow_sheet if self._instrument is not None else column
        if model_arg is None or model_fn is None:
            self._models.clear()
            self._process.clear()
            self._sync_column_bypass()
            self.persistence.refresh_hash_display()
            return

        # The template is rebuilt from scratch every time, so its method values are
        # carried over until the template, binding model or components change.
        model_key = (model_fn, self._binding_picker.value, tuple(self._components.value))
        previous_model = (
            self._model_form.collect_values()
            if self._model_form is not None and model_key == self._model_key else None
        )
        self._model_key = model_key

        # A bound instrument hands out a fresh column on every rebuild, so the forms
        # carry their values over when their shape is unchanged.
        self._models.rebuild(
            column, binding_model, self._components.value, carry=self._instrument is not None
        )
        self._sync_column_bypass()

        self._model_form = FormRenderer(
            model_fn(model_arg),
            on_built=self._on_process_built,
            on_reset=lambda: self._reset_form("model"),
        )
        if previous_model is not None:
            self._model_form.set_values(previous_model)
        self._process.show_form()
        # The model form's `on_built` fires inside its constructor, before `_model_form` is
        # assigned, so the hash must be refreshed again here.
        self.persistence.refresh_hash_display()
        self._apply_starting_values(method=previous_model is None)

        self.status.value = (
            "<em>Fields apply automatically as you edit them"
            " (column and binding model first, since the process picks up"
            " whatever's currently set on them).</em>"
        )

    def _rebuild_event_sliders(self) -> None:
        self._process.rebuild_event_sliders()

    def _apply_starting_values(self, *, method: bool) -> None:
        """Fill the shared starting values into freshly built forms (see `starting_values`).

        Method values are only used while the process template is shown and with `method`.
        """
        if self._restoring or not self.use_starting_values:
            return
        state = self.snapshot()
        seeded = self._seeded(state, method=method)
        if seeded != state:
            self._apply_state(self.config_name, seeded)

    def _seeded(self, state: ConfigurationState, *, method: bool) -> ConfigurationState:
        shown = self.show_process_template
        seeded = with_starting_values(state, method=shown and method, equilibrate=shown)
        known = getattr(COLUMN_MODELS.get(state.column_key), "_parameters", ())
        return dataclasses.replace(seeded, column_values={
            k: v for k, v in seeded.column_values.items() if k in known
        })

    def _reset_form(self, part: str) -> None:
        """Reset one form ("column", "binding" or "model") to its defaults.

        Column and binding fields take a fresh model's defaults, the method fields the
        template's; with standard starting values on, those are filled in on top.
        """
        form = {
            "column": self._column_form, "binding": self._binding_form, "model": self._model_form,
        }[part]
        if form is None:
            return
        defaults = form.default_values()
        column, binding_model = self._form_objects()
        obj = {"column": column, "binding": binding_model}.get(part)
        if obj is not None:
            multiplex = self._models.multiplex_state if part == "column" else None
            defaults.update(parameter_defaults(obj, list(defaults), multiplex=multiplex))
        state = dataclasses.replace(self.snapshot(), **{f"{part}_values": defaults})
        if self.use_starting_values:
            state = self._seeded(state, method=part == "model")
        self._apply_state(self.config_name, state)

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
