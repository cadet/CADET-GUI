from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import (
    BINDING_MODELS,
    BYPASSABLE_UNITS,
    COLUMN_MODELS,
    ModelSpec,
    build_parameter_config_spec,
    require_finite_above,
)
from ...cadetprocessadapter import (
    UNIT_LABELS as _UNIT_LABELS,
)
from ...configuration_store import InstrumentState
from .._chrome import style_tag
from .._settings_popover import toggle_box
from .._status import status_html
from ..elements import ChoiceField, FloatField
from ..forms import FormRenderer
from .system_diagram import SystemDiagram

__all__ = ["InstrumentWidget"]


# Narrow, deliberate scope: real per-parameter forms now exist for these five
# (mixer + tubing), but "column" isn't one of them -- ConfigurationWidget
# already owns the column's own parameter form; this widget only ever
# contributes the toggle for whether it's in the flow path at all.
_CONFIGURABLE_UNITS = (
    "mixer", "tubing_pre_injection", "tubing_pre_column", "tubing_post_column", "tubing_detectors",
)

# Starting values so a freshly-included unit isn't degenerate (zero volume/
# length); CADET-Core has no canonical default for these, same spirit as
# cadetprocessadapter.py's _GUI_SEED_DEFAULTS. Overridden per-unit, forever
# after, by whatever the user actually commits through that unit's own form
# (see _unit_values/_on_unit_built).
_TUBING_SEED_DEFAULTS: Dict[str, float] = {
    "diameter": 0.5e-3, "length": 0.1, "axial_dispersion": 1e-7,
}
_UNIT_SEED_DEFAULTS: Dict[str, Dict[str, float]] = {
    "mixer": {"init_liquid_volume": 1e-6},
    "tubing_pre_injection": _TUBING_SEED_DEFAULTS,
    "tubing_pre_column": _TUBING_SEED_DEFAULTS,
    "tubing_post_column": _TUBING_SEED_DEFAULTS,
    "tubing_detectors": _TUBING_SEED_DEFAULTS,
}

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


# Physical order of the flow path (ARCHITECTURE.md: "buffer inlets -> mixer
# -> optional sample loop -> tubing segments -> column -> tubing -> outlet").
# Sample loop itself is rendered as its own subsection, spliced in here.
_UNIT_ORDER = (
    "mixer", "tubing_pre_injection", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors",
)


class InstrumentWidget:
    """Configure an LC-system topology on top of a column/binding *choice* it's given.

    Optional layer (REQUIREMENTS.md item #32): `ConfigurationWidget` already
    builds a standalone bare-column simulation without one of these bound.
    Binding an `InstrumentWidget` adds a real LC-system flow path around that
    same column/binding choice -- sample loop, and which units (mixer, tubing,
    the column itself) are actually part of the flow path, each with its own
    real parameter form (mixer/tubing dead-volume geometry -- "Units In Flow
    Path" was previously just inclusion toggles with hardcoded seed values,
    see ARCHITECTURE.md).

    The LC topology is always in effect when this widget is used: a bound
    `ConfigurationWidget` builds its process around `.flow_sheet`. A
    `ConfigurationWidget` with no instrument bound still builds the
    standalone process directly, including `Cstr` (not a
    `ChromatographicColumnBase`, so it can never fill `LCFlowSheet`'s column
    slot) and the 'Pulse Feed (Single Component)' template.

    The sample loop is off by default and optional; a bound
    `ConfigurationWidget` switches it on and locks it (`set_required_units`)
    while the selected process template can't be built without one.

    Component names and column/binding *type* live on the composing
    `ConfigurationWidget` (its own pickers there "win" -- see
    ARCHITECTURE.md) and are handed in here via `.components` and
    `set_column_and_binding()` rather than owned by this widget's own UI --
    both default to something sane (one generic component, LRM/Linear) so
    this widget still builds a real flow sheet dropped standalone into a
    notebook cell (EXT-001). Builds and exposes `.flow_sheet`, auto-committing
    on every valid change; `add_listener` fires with it on every build. While
    any System input is invalid the offending field shows the error,
    `.flow_sheet` is `None` and listeners are told so -- never a stale sheet
    that contradicts the visible fields.

    The unit toggles, sample-loop controls and per-unit forms live in one
    collapsible "Hardware in the flow path" section below the diagram and
    template picker. `hardware_expanded` sets its initial state (collapsed by
    default; see `set_hardware_expanded` / `.hardware_expanded`). Collapsing only
    hides the controls: every toggle keeps applying and a one-line summary of
    the enabled hardware stays next to the header. `apply_state` expands the
    section when the loaded state has non-default hardware (never collapses it).

    The column toggle is only offered with `allow_column_bypass=True`
    (characterizing the periphery without a column). Otherwise it is hidden --
    unless the column is already bypassed, e.g. by a loaded configuration, so
    the state can always be undone.
    """

    def __init__(
        self, *, hardware_expanded: bool = False, allow_column_bypass: bool = False
    ) -> None:
        self._allow_column_bypass = allow_column_bypass
        self._listeners: List[Callable[[Any], None]] = []
        self._built_sheet: Optional[LCFlowSheet] = None
        self._problems: Dict[str, str] = {}
        # Set around apply_state()'s field writes so each one's own observer
        # doesn't trigger its own rebuild -- one rebuild for the whole
        # restored selection instead of one per field touched.
        self._suspend_rebuild = False

        self._component_names: List[str] = ["Component 1"]
        self._column_cls: Optional[type] = COLUMN_MODELS.get(
            "Lumped Rate Model Without Pores (LRM)"
        )
        self._binding_cls: Optional[type] = BINDING_MODELS.get("Linear")

        # Per-unit parameter values, persisted across rebuilds (a fresh
        # LCFlowSheet -- and so fresh mixer/tubing instances -- is built on
        # every change, even one unrelated to a given unit's own fields) --
        # see _rebuild_unit_forms/_make_on_unit_built.
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

        # Only "column" starts checked; mixer/tubing segments are opt-in.
        self._unit_checkboxes: Dict[str, W.Checkbox] = {
            name: W.Checkbox(
                description=_UNIT_LABELS[name], value=(name == "column"), indent=False
            )
            for name in BYPASSABLE_UNITS
        }
        # Filled in by _rebuild_unit_forms() with each configurable unit's
        # own FormRenderer; stays empty (no form) for "column".
        self._unit_form_boxes: Dict[str, W.VBox] = {
            name: W.VBox([]) for name in _CONFIGURABLE_UNITS
        }

        self._active_inlets: Optional[List[str]] = None
        self._carries: Optional[Mapping[str, Sequence[str]]] = None
        self._equilibration: Sequence[str] = ()
        self._column_label: Optional[str] = None
        self._diagram = SystemDiagram()
        self._on_template_select: Optional[Callable[[str], None]] = None
        self._syncing_template = False
        self._template_picker = ChoiceField(label="Process template:")
        self._template_picker.layout.display = "none"
        self._template_picker.observe(self._on_template_change, names="selected_index")

        self.status = W.HTML("<em>Building the system...</em>")
        self.status.add_class("cadetgui-status")

        # Two nesting levels, not one: each unit's own toggle sits at the
        # "Units In Flow Path" level, and whatever it controls (its
        # parameter form, or the sample loop's volume/diameter fields) is
        # nested a level deeper -- e.g. "Auto-derive diameter from volume"
        # must not read as a peer of "Sample loop" itself.
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
                # Physical order: mixer, then the optional sample loop.
                unit_subsections.append(sample_loop_subsection)

        self._column_box = self._unit_boxes["column"]
        self._flow_path_note = W.HTML("", layout=W.Layout(margin="0 0 4px 0"))
        self._hardware_body = W.VBox([self._flow_path_note, *unit_subsections])
        self._hardware_toggle = W.Button(
            description="Hardware in the flow path", icon="chevron-right",
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
        """Whether the "Hardware in the flow path" controls are currently shown."""
        return self._hardware_body.layout.display != "none"

    def set_hardware_expanded(self, expanded: bool) -> None:
        """Show or hide the hardware controls; the summary line stays visible either way."""
        self._hardware_body.layout.display = "" if expanded else "none"
        self._hardware_toggle.icon = "chevron-down" if expanded else "chevron-right"

    def _on_hardware_toggle(self, _btn: Any) -> None:
        self.set_hardware_expanded(toggle_box(self._hardware_body))

    @property
    def column_toggle_visible(self) -> bool:
        """Whether the column on/off checkbox is currently offered."""
        return self._column_box.layout.display != "none"

    def _refresh_hardware_summary(self) -> None:
        column_on = self._unit_checkboxes["column"].value
        show_column_toggle = self._allow_column_bypass or not column_on
        self._column_box.layout.display = "" if show_column_toggle else "none"
        self._flow_path_note.value = (
            "<em>Uncheck a unit to remove it from the flow path -- e.g. to characterize "
            "the system before adding a column.</em>"
            if self._allow_column_bypass
            else "<em>Check the hardware that should be part of the simulated flow path.</em>"
        )

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

        head = "Column" if column_on else "No column"
        if extras:
            text = f"{head} + {', '.join(extras)}"
        else:
            text = "Column only" if column_on else "No column"
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
        """Current component names -- externally driven, see class docstring."""
        return list(self._component_names)

    @components.setter
    def components(self, names: List[str]) -> None:
        self._component_names = list(names)
        if not self._suspend_rebuild:
            self._rebuild()

    def set_column_and_binding(
        self,
        column_cls: Optional[type],
        binding_cls: Optional[type],
        column_label: Optional[str] = None,
    ) -> None:
        """Externally driven column/binding *type* choice -- see class docstring.

        `column_label` is the column model's name captioned under the column in the diagram.
        """
        self._column_label = column_label
        self._column_cls = column_cls
        self._binding_cls = binding_cls
        if not self._suspend_rebuild:
            self._rebuild()

    def set_active_inlets(
        self,
        names: Optional[Iterable[str]],
        carries: Optional[Mapping[str, Sequence[str]]] = None,
        equilibration: Sequence[str] = (),
    ) -> None:
        """Set which inlets the selected process drives (`None`: unknown) and redraw the diagram.

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
        """Offer process templates next to the diagram; picking one calls `on_select(label)`.

        Only the label list and the selection are mirrored here -- the owner of the template
        choice stays the single source of truth (see `select_template`).
        """
        self._on_template_select = on_select
        self._syncing_template = True
        try:
            self._template_picker.set_options([(label, label) for label in labels])
            self._template_picker.value = selected
        finally:
            self._syncing_template = False
        self._template_picker.layout.display = "" if labels else "none"

    def select_template(self, label: Optional[str]) -> None:
        """Show `label` as the selected template without firing the selection callback."""
        self._syncing_template = True
        try:
            self._template_picker.value = label
        finally:
            self._syncing_template = False

    def _on_template_change(self, change: dict) -> None:
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
        if change.get("name") not in ("value", "selected_index"):
            return
        if change.get("owner") is self._sample_loop_checkbox and not self._loop_locked:
            self._loop_user_choice = bool(self._sample_loop_checkbox.value)
        self._apply_loop_field_visibility()
        self._refresh_hardware_summary()
        if self._suspend_rebuild:
            return
        self._rebuild()

    def set_required_units(self, units: Iterable[str], *, reason: str = "") -> None:
        """Force the units a process template can't be built without into the flow path.

        Only `"sample_loop"` is supported. A required unit is switched on and
        locked with a note naming `reason`; once no longer required, the
        checkbox unlocks and returns to the user's own last choice.
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
            # Collapse CADET-Process's list-wrapped scalars (every field here
            # is a plain, non-multiplexed FloatField -- see
            # cadetprocessadapter.py's `_FORCE_SCALAR` for "TubularReactor")
            # back to the bare float the form itself shows, not the raw
            # (possibly `[v]`-wrapped) attribute.
            values = {}
            for p in getattr(built, "required_parameters", []):
                v = getattr(built, p)
                values[p] = v[0] if isinstance(v, (list, tuple)) else v
            self._unit_values[name] = values
            self._resolve_problem(_UNIT_LABELS[name])

        return _on_built

    def _make_on_unit_invalid(self, name: str) -> Callable[[str], None]:
        def _on_invalid(message: str) -> None:
            self._report_problem(_UNIT_LABELS[name], message)

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
        """(Re)build each configurable unit's own parameter form against the fresh flow sheet.

        A brand-new LCFlowSheet -- and so brand-new mixer/tubing instances --
        is built on every `_rebuild()`, so this seeds each unit from
        `_unit_values` (falling back to the hardcoded starting defaults the
        first time) before building its form, rather than losing whatever the
        user last committed through it.

        `"mixer"` needs its own bypass check (`name in bypass`), not just
        `name not in flow_sheet`: `LCFlowSheet` never actually removes it --
        it's always needed as the buffer junction -- and forces its own
        `init_liquid_volume = 1e-9` bypass value instead (per its own
        docstring). Applying a persisted/seed value on top of that would
        silently undo the bypass.
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

        try:
            cs = ComponentSystem(list(self._component_names))
            bypass = self.bypass_units()
            include_loop = bool(self._sample_loop_checkbox.value)
            loop_volume = float(self._loop_volume_field.value) if include_loop else None
            loop_diameter = None
            if include_loop and not self._loop_diameter_auto_checkbox.value:
                loop_diameter = float(self._loop_diameter_field.value)
            column_cls = None if "column" in bypass else self._column_cls
            binding_cls = self._binding_cls

            flow_sheet = LCFlowSheet(
                cs,
                sample_loop_volume=loop_volume,
                sample_loop_diameter=loop_diameter,
                ColumnModel=column_cls,
                BindingModel=binding_cls,
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
