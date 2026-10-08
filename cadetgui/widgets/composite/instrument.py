from __future__ import annotations

from dataclasses import replace
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
)

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    BINDING_MODELS,
    BYPASSABLE_UNITS,
    COLUMN_MODELS,
    CONFIGURABLE_UNITS,
    UNIT_LABELS,
    UNIT_SEED_DEFAULTS,
    ModelSpec,
    build_parameter_config_spec,
    require_finite_above,
)
from ...io.configuration_store import InstrumentState
from .._chrome import style_tag
from .._settings_popover import toggle_box
from .._status import status_html
from ..elements import ChoiceField, ComponentListField, FloatField
from ..forms import FormRenderer
from .system_diagram import SystemDiagram

if TYPE_CHECKING:
    from ...characterization.study import Study
    from .study_components import StudyComponentsWidget

__all__ = ["InstrumentWidget"]


# The column's own form belongs to ConfigurationWidget; this widget only toggles it.
_CONFIGURABLE_UNITS = CONFIGURABLE_UNITS
_UNIT_SEED_DEFAULTS = UNIT_SEED_DEFAULTS

_ZERO_ALLOWED_PARAMS = frozenset({"axial_dispersion"})

_TUBING_SHORT_LABELS = {
    "tubing_pre_injection": "pre-injection",
    "tubing_pre_column": "pre-column",
    "tubing_post_column": "post-column",
    "tubing_detectors": "detectors",
}
_DEFAULT_BYPASS = frozenset(BYPASSABLE_UNITS) - {"column"}


def _with_bounds_validation(spec: ModelSpec) -> ModelSpec:
    """Give every scalar float field a validator: finite, and above (or at) its lower bound."""
    fields = []
    for f in spec.fields:
        if f.kind == "float" and f.validate is None:
            minimum = f.min if f.min is not None else 0.0
            inclusive = f.name in _ZERO_ALLOWED_PARAMS or minimum < 0
            f = replace(f, validate=require_finite_above(minimum, inclusive=inclusive))
        fields.append(f)
    return replace(spec, fields=fields)


# Physical order of the flow path; the sample loop is spliced in after the mixer.
_UNIT_ORDER = (
    "mixer", "tubing_pre_injection", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors",
)


class InstrumentWidget:
    """Configure an LC-system topology around a column/binding choice it is given.

    Optional layer on top of `ConfigurationWidget`: adds a sample loop and the choice of
    which units (mixer, tubing, the column itself) are in the flow path, each with its own
    parameter form. The "Components" section above the hardware edits the component names
    (also settable via `.components`); the column/binding types are driven from outside via
    `set_column_and_binding()`. Both default to something sane so the widget also builds a
    flow sheet on its own. `bind_study(study)` turns the Components section into an editor
    of `study.components` (name and role) that the component names follow.

    Builds `.flow_sheet`, auto-committing on every valid change; `add_listener` fires with
    it on every build. While any input is invalid the offending field shows the error,
    `.flow_sheet` is `None` and listeners are told so.

    The sample loop is off by default; a bound `ConfigurationWidget` switches it on and locks
    it (`set_required_units`) while the selected template can't be built without one.

    The unit toggles, sample-loop controls and per-unit forms live in a collapsible
    "Hardware" section (`hardware_expanded` sets its initial state).
    Collapsing only hides the controls; a one-line summary stays visible.

    With `hardware_only`, the diagram shows the installed hardware without the inlet use of
    a process and no process-template picker is shown (see `SystemDiagram`).
    """

    def __init__(self, *, hardware_expanded: bool = False, hardware_only: bool = False) -> None:
        self.hardware_only = hardware_only
        self._listeners: List[Callable[[Any], None]] = []
        self._built_sheet: Optional[LCFlowSheet] = None
        self._problems: Dict[str, str] = {}
        # Set around apply_state()'s field writes so the restored state rebuilds once.
        self._suspend_rebuild = False

        self._component_names: List[str] = ["Component 1"]
        self._syncing_components = False
        self._study: Optional["Study"] = None
        self._study_names: List[str] = []
        self.study_components: Optional["StudyComponentsWidget"] = None
        self._components_field = ComponentListField(
            label="Components:", value=self._component_names
        )
        self._components_note = W.HTML("", layout=W.Layout(display="none"))
        self._components_section = W.VBox([
            W.HTML("<div class='cadetgui-section-title'>Components</div>"),
            self._components_field,
            self._components_note,
        ])
        self._components_section.add_class("cadetgui-section")
        self._components_field.observe(self._on_components_edit, names="value")
        self._column_cls: Optional[type] = COLUMN_MODELS.get(
            "Lumped Rate Model Without Pores (LRM)"
        )
        self._binding_cls: Optional[type] = BINDING_MODELS.get("Linear")

        # Every rebuild creates fresh mixer/tubing instances, so their values live here.
        self._unit_values: Dict[str, Dict[str, float]] = {}
        self._unit_forms: Dict[str, FormRenderer] = {}

        self._sample_loop_checkbox = W.Checkbox(
            description="Sample loop", value=False, indent=False
        )
        self._loop_locked = False
        self._loop_user_choice = False
        self._loop_lock_note = W.HTML("", layout=W.Layout(display="none"))
        self._loop_volume_field = FloatField(
            label="Sample loop volume", value=50e-9, units=r"\mathrm{m}^{3}",
            validate=self._validate_loop_volume,
        )
        self._loop_diameter_auto_checkbox = W.Checkbox(
            description="Auto-derive diameter from volume", value=True, indent=False
        )
        self._loop_diameter_field = FloatField(
            label="Sample loop diameter", value=0.75e-3, units=r"\mathrm{m}",
            validate=self._validate_loop_diameter,
        )

        self._unit_checkboxes: Dict[str, W.Checkbox] = {
            name: W.Checkbox(
                description=UNIT_LABELS[name], value=(name == "column"), indent=False
            )
            for name in BYPASSABLE_UNITS
        }
        self._unit_form_boxes: Dict[str, W.VBox] = {
            name: W.VBox([]) for name in _CONFIGURABLE_UNITS
        }

        self._active_inlets: Optional[List[str]] = None
        self._carries: Optional[Mapping[str, Sequence[str]]] = None
        self._equilibration: Sequence[str] = ()
        self._column_label: Optional[str] = None
        self._diagram = SystemDiagram(hardware_only=hardware_only)
        self._on_template_select: Optional[Callable[[str], None]] = None
        self._syncing_template = False
        self._template_picker = ChoiceField(label="Process template:")
        self._template_picker.layout.display = "none"
        self._template_picker.observe(self._on_template_change, names="selected_index")

        self.status = W.HTML("<em>Building the system...</em>")
        self.status.add_class("cadetgui-status")

        # What a toggle controls nests one level deeper than the toggle itself.
        sample_loop_fields = W.VBox(
            [self._loop_volume_field, self._loop_diameter_auto_checkbox, self._loop_diameter_field]
        )
        sample_loop_fields.add_class("cadetgui-subsection")
        sample_loop_subsection = W.VBox(
            [self._sample_loop_checkbox, self._loop_lock_note, sample_loop_fields]
        )
        sample_loop_subsection.add_class("cadetgui-subsection")

        unit_subsections = []
        self._unit_boxes: Dict[str, W.VBox] = {}
        for name in _UNIT_ORDER:
            children = [self._unit_checkboxes[name]]
            if name in self._unit_form_boxes:
                self._unit_form_boxes[name].add_class("cadetgui-subsection")
                children.append(self._unit_form_boxes[name])
            box = W.VBox(children)
            box.add_class("cadetgui-subsection")
            self._unit_boxes[name] = box
            unit_subsections.append(box)
            if name == "mixer":
                unit_subsections.append(sample_loop_subsection)

        self._flow_path_note = W.HTML(
            "<em>Uncheck a unit to remove it from the flow path -- e.g. to characterize "
            "the system before adding a column.</em>",
            layout=W.Layout(margin="0 0 4px 0"),
        )
        self._hardware_body = W.VBox([self._flow_path_note, *unit_subsections])
        self._hardware_toggle = W.Button(
            description="Hardware", icon="chevron-right",
            tooltip="Show or hide the units in the flow path",
        )
        self._hardware_summary = W.HTML("", layout=W.Layout(margin="0 0 0 10px"))
        self._hardware_summary.add_class("cadetgui-hardware-summary")
        self._hardware_toggle.on_click(self._on_hardware_toggle)
        self._flow_path_section = W.VBox(
            [
                W.HBox(
                    [self._hardware_toggle, self._hardware_summary],
                    layout=W.Layout(align_items="center"),
                ),
                self._hardware_body,
            ]
        )
        self._flow_path_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>System</div>"),
                self._template_picker,
                self._components_section,
                self._diagram.root,
                self._flow_path_section,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._sample_loop_checkbox.observe(self._on_change, names="value")
        self._loop_volume_field.observe(self._on_change, names="value")
        self._loop_diameter_auto_checkbox.observe(self._on_change, names="value")
        self._loop_diameter_field.observe(self._on_change, names="value")
        for checkbox in self._unit_checkboxes.values():
            checkbox.observe(self._on_change, names="value")

        self._apply_loop_field_visibility()
        self.set_hardware_expanded(hardware_expanded)
        self._refresh_hardware_summary()
        self._rebuild()

    @property
    def hardware_expanded(self) -> bool:
        """Whether the "Hardware" controls are currently shown."""
        return self._hardware_body.layout.display != "none"

    def set_hardware_expanded(self, expanded: bool) -> None:
        """Show or hide the hardware controls; the summary line stays visible either way."""
        self._hardware_body.layout.display = "" if expanded else "none"
        self._hardware_toggle.icon = "chevron-down" if expanded else "chevron-right"

    def set_highlight(self, units: Collection[str], observe: Optional[str] = None) -> None:
        """Highlight `units` and the observed outlet `observe` on the diagram."""
        self._diagram.set_highlight(units, observe)

    def _on_hardware_toggle(self, _btn: Any) -> None:
        self.set_hardware_expanded(toggle_box(self._hardware_body))

    def _refresh_hardware_summary(self) -> None:
        column_on = self._unit_checkboxes["column"].value
        extras = []
        if self._unit_checkboxes["mixer"].value:
            extras.append("mixer")
        if self._sample_loop_checkbox.value:
            extras.append(
                "sample loop (required by template)" if self._loop_locked else "sample loop"
            )
        tubing = [
            short for unit, short in _TUBING_SHORT_LABELS.items()
            if self._unit_checkboxes[unit].value
        ]
        if tubing:
            extras.append(f"tubing ({', '.join(tubing)})")

        if not extras:
            text = "Column only" if column_on else "No column"
        else:
            text = f"{'Column' if column_on else 'No column'} + {', '.join(extras)}"
        self._hardware_summary.value = text

    @property
    def flow_sheet(self) -> Optional[LCFlowSheet]:
        """The current LC flow sheet, or `None` while any System input is invalid."""
        return None if self._problems else self._built_sheet

    def _validate_loop_volume(self, value: Any) -> None:
        if self._sample_loop_checkbox.value:
            require_finite_above()(value)

    def _validate_loop_diameter(self, value: Any) -> None:
        if self._sample_loop_checkbox.value and not self._loop_diameter_auto_checkbox.value:
            require_finite_above()(value)

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.flow_sheet` on every successful build."""
        self._listeners.append(fn)

    @property
    def components(self) -> List[str]:
        """Current component names, driven by the owning `ConfigurationWidget`."""
        return list(self._component_names)

    @components.setter
    def components(self, names: List[str]) -> None:
        self._component_names = list(names)
        if list(self._components_field.value) != self._component_names:
            self._syncing_components = True
            try:
                self._components_field.value = list(self._component_names)
            finally:
                self._syncing_components = False
        if not self._suspend_rebuild:
            self._rebuild()

    def _on_components_edit(self, change: dict) -> None:
        if not self._syncing_components:
            self.components = list(change["new"])

    def set_min_components(self, count: int, note: str = "") -> None:
        """Keep at least `count` component names; `note` explains why (hidden when empty)."""
        self._components_field.min_components = count
        self._components_note.value = f"<em>{note}</em>" if note else ""
        self._components_note.layout.display = "" if note else "none"

    def bind_study(self, study: "Study") -> None:
        """Edit `study.components` (name and role) in the Components section.

        The component names follow the study's list (salt first) whenever it changes.
        """
        from .study_components import StudyComponentsWidget

        self._study = study
        self.study_components = StudyComponentsWidget(study)
        self.study_components.root.remove_class("cadetgui-section")
        self._components_section.children = (
            self.study_components.root, self._components_note,
        )
        study.add_listener(self._sync_from_study)
        self._sync_from_study()

    def _sync_from_study(self) -> None:
        names = [c.name for c in self._study.components]
        if names and names != self._study_names:
            self._study_names = names
            self.components = names

    def set_column_and_binding(
        self,
        column_cls: Optional[type],
        binding_cls: Optional[type],
        column_label: Optional[str] = None,
    ) -> None:
        """Set the column/binding types; `column_label` is captioned under the column."""
        self._column_label = column_label
        self._column_cls = column_cls
        self._binding_cls = binding_cls
        if not self._suspend_rebuild:
            self._rebuild()

    def add_section(self, section: W.Widget, *, after_components: bool = False) -> None:
        """Show `section` below the hardware (or right after Components), above the status."""
        children = list(self.root.children)
        index = (
            children.index(self._components_section) + 1 if after_components
            else children.index(self.status)
        )
        children.insert(index, section)
        self.root.children = tuple(children)

    def set_active_inlets(
        self,
        names: Optional[Iterable[str]],
        carries: Optional[Mapping[str, Sequence[str]]] = None,
        equilibration: Sequence[str] = (),
    ) -> None:
        """Set which inlets the process drives (`None`: unknown) and redraw the diagram.

        `carries` maps each driven inlet to the component names it delivers; `equilibration`
        lists inlets that only pre-equilibrate the system.
        """
        self._active_inlets = None if names is None else list(names)
        self._carries = carries
        self._equilibration = tuple(equilibration)
        self._refresh_diagram()

    def set_template_options(
        self,
        labels: Sequence[str],
        selected: Optional[str],
        on_select: Callable[[str], None],
    ) -> None:
        """Mirror the owner's template choice next to the diagram; picking one calls `on_select`."""
        self._on_template_select = on_select
        self._syncing_template = True
        try:
            self._template_picker.set_options([(label, label) for label in labels])
            self._template_picker.value = selected
        finally:
            self._syncing_template = False
        self._template_picker.layout.display = (
            "" if labels and not self.hardware_only else "none"
        )

    def select_template(self, label: Optional[str]) -> None:
        """Show `label` as the selected template without firing the selection callback."""
        self._syncing_template = True
        try:
            self._template_picker.value = label
        finally:
            self._syncing_template = False

    def _on_template_change(self, _change: dict) -> None:
        if self._syncing_template or self._on_template_select is None:
            return
        label = self._template_picker.value
        if label is not None:
            self._on_template_select(label)

    def _refresh_diagram(self) -> None:
        self._diagram.update(
            self.flow_sheet, self.bypass_units(), self._active_inlets, self._carries,
            self._equilibration, self._column_label,
        )

    def _notify(self) -> None:
        self._refresh_diagram()
        for fn in list(self._listeners):
            fn(self.flow_sheet)

    def _on_change(self, change: dict) -> None:
        if change["owner"] is self._sample_loop_checkbox and not self._loop_locked:
            self._loop_user_choice = bool(self._sample_loop_checkbox.value)
        self._apply_loop_field_visibility()
        self._refresh_hardware_summary()
        if self._suspend_rebuild:
            return
        self._rebuild()

    def set_required_units(self, units: Iterable[str], *, reason: str = "") -> None:
        """Force the units a template can't be built without into the flow path.

        Only `"sample_loop"` is supported: it is switched on and locked with a note naming
        `reason`, and returns to the user's own last choice once no longer required.
        """
        required = frozenset(units)
        unknown = required - {"sample_loop"}
        if unknown:
            raise ValueError(f"Unsupported required units: {sorted(unknown)}")
        if "sample_loop" in required:
            if not self._loop_locked:
                self._loop_user_choice = bool(self._sample_loop_checkbox.value)
                self._loop_locked = True
            self._sample_loop_checkbox.disabled = True
            self._loop_lock_note.value = f"<em>{reason or 'This process'} needs a sample loop.</em>"
            self._loop_lock_note.layout.display = ""
            self._sample_loop_checkbox.value = True
        elif self._loop_locked:
            self._loop_locked = False
            self._sample_loop_checkbox.disabled = False
            self._loop_lock_note.layout.display = "none"
            self._sample_loop_checkbox.value = self._loop_user_choice
        self._refresh_hardware_summary()

    def snapshot(self) -> InstrumentState:
        """Capture the current topology selection as the hashed save/import payload."""
        return InstrumentState(
            include_sample_loop=bool(self._sample_loop_checkbox.value),
            sample_loop_volume=float(self._loop_volume_field.value),
            sample_loop_diameter_auto=bool(self._loop_diameter_auto_checkbox.value),
            sample_loop_diameter=float(self._loop_diameter_field.value),
            bypass_units=self.bypass_units(),
            unit_values={k: dict(v) for k, v in self._unit_values.items()},
        )

    def apply_state(self, state: InstrumentState) -> None:
        """Reconstruct fields from a saved InstrumentState."""
        self._suspend_rebuild = True
        try:
            # A locked loop is on because of the template, not the user's choice.
            if not self._loop_locked:
                self._loop_user_choice = state.include_sample_loop
            self._sample_loop_checkbox.value = state.include_sample_loop or self._loop_locked
            self._loop_volume_field.value = state.sample_loop_volume
            self._loop_diameter_auto_checkbox.value = state.sample_loop_diameter_auto
            self._loop_diameter_field.value = state.sample_loop_diameter
            for name, checkbox in self._unit_checkboxes.items():
                checkbox.value = name not in state.bypass_units
            self._unit_values = {k: dict(v) for k, v in state.unit_values.items()}
        finally:
            self._suspend_rebuild = False

        self._apply_loop_field_visibility()
        self._refresh_hardware_summary()
        if state.include_sample_loop or set(state.bypass_units) != _DEFAULT_BYPASS:
            self.set_hardware_expanded(True)
        self._rebuild()

    def _apply_loop_field_visibility(self) -> None:
        include_loop = self._sample_loop_checkbox.value
        self._loop_volume_field.layout.display = "" if include_loop else "none"
        self._loop_diameter_auto_checkbox.layout.display = "" if include_loop else "none"
        auto = self._loop_diameter_auto_checkbox.value
        self._loop_diameter_field.layout.display = "" if (include_loop and not auto) else "none"
        self._loop_volume_field._run_validate()
        self._loop_diameter_field._run_validate()

    def bypass_units(self) -> List[str]:
        """Currently-unchecked unit names -- excluded from the flow path."""
        return [name for name, cb in self._unit_checkboxes.items() if not cb.value]

    def _make_on_unit_built(self, name: str) -> Callable[[Any], None]:
        def _on_built(built: Any) -> None:
            # CADET-Process may list-wrap these scalars; store the bare float the form shows.
            values = {}
            for p in getattr(built, "required_parameters", []):
                v = getattr(built, p)
                values[p] = v[0] if isinstance(v, (list, tuple)) else v
            self._unit_values[name] = values
            self._resolve_problem(UNIT_LABELS[name])

        return _on_built

    def _make_on_unit_invalid(self, name: str) -> Callable[[str], None]:
        def _on_invalid(message: str) -> None:
            self._report_problem(UNIT_LABELS[name], message)

        return _on_invalid

    def _report_problem(self, source: str, message: str) -> None:
        was_valid = not self._problems
        self._problems[source] = message
        self._refresh_status()
        if was_valid:
            self._notify()

    def _resolve_problem(self, source: str) -> None:
        if self._problems.pop(source, None) is None:
            return
        self._refresh_status()
        if not self._problems and self._built_sheet is not None:
            self._notify()

    def _refresh_status(self) -> None:
        if self._problems:
            detail = "; ".join(f"{source}: {message}" for source, message in self._problems.items())
            self.status.value = status_html("error", f"Invalid System inputs -- {detail}")
        else:
            self.status.value = "<em>System built.</em>"

    def _rebuild_unit_forms(self, flow_sheet: LCFlowSheet, bypass: List[str]) -> None:
        """Rebuild each configurable unit's form against the fresh flow sheet.

        Units are seeded from `_unit_values` (or the starting defaults) first. The mixer needs
        the explicit bypass check: `LCFlowSheet` never removes it and forces its own bypass
        volume, which a seeded value would silently undo.
        """
        self._unit_forms = {}
        for name in _CONFIGURABLE_UNITS:
            box = self._unit_form_boxes[name]
            if name in bypass or name not in flow_sheet:
                box.children = ()
                continue
            unit = flow_sheet[name]
            for pname, value in (self._unit_values.get(name) or _UNIT_SEED_DEFAULTS[name]).items():
                setattr(unit, pname, value)
            form = FormRenderer(
                _with_bounds_validation(build_parameter_config_spec(unit)),
                on_built=self._make_on_unit_built(name),
                on_invalid=self._make_on_unit_invalid(name),
            )
            self._unit_forms[name] = form
            box.children = (form.root,)

    def _loop_field_problems(self) -> Dict[str, str]:
        problems = {}
        for label, element in (
            ("Sample loop volume", self._loop_volume_field),
            ("Sample loop diameter", self._loop_diameter_field),
        ):
            if element.error:
                problems[label] = element.error
        return problems

    def _rebuild(self) -> None:
        self._problems = self._loop_field_problems()
        if self._problems:
            self._built_sheet = None
            self._refresh_status()
            self._notify()
            return

        bypass = self.bypass_units()
        include_loop = bool(self._sample_loop_checkbox.value)
        try:
            flow_sheet = LCFlowSheet(
                ComponentSystem(list(self._component_names)),
                sample_loop_volume=float(self._loop_volume_field.value) if include_loop else None,
                sample_loop_diameter=(
                    float(self._loop_diameter_field.value)
                    if include_loop and not self._loop_diameter_auto_checkbox.value
                    else None
                ),
                ColumnModel=None if "column" in bypass else self._column_cls,
                BindingModel=self._binding_cls,
                bypass_units=bypass or None,
            )
        except Exception as exc:  # noqa: BLE001
            self._built_sheet = None
            self._problems = {"System": str(exc)}
            self._refresh_status()
            self._notify()
            return

        self._built_sheet = flow_sheet
        self._rebuild_unit_forms(flow_sheet, bypass)
        self._refresh_status()
        self._notify()

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
