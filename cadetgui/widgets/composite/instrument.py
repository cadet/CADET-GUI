from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

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
from ...configuration_store import InstrumentState
from .._chrome import style_tag
from .._status import status_html
from ..elements import FloatField
from ..forms import FormRenderer

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


_UNIT_LABELS: Dict[str, str] = {
    "mixer": "Mixer",
    "tubing_pre_injection": "Tubing (pre injection)",
    "tubing_pre_column": "Tubing (pre column)",
    "column": "Column",
    "tubing_post_column": "Tubing (post column)",
    "tubing_detectors": "Tubing (detectors)",
}

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
    """

    def __init__(self) -> None:
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
            description="Sample loop", value=True, indent=False
        )
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
        sample_loop_subsection = W.VBox([self._sample_loop_checkbox, sample_loop_fields])
        sample_loop_subsection.add_class("cadetgui-subsection")

        unit_subsections = []
        for name in _UNIT_ORDER:
            children = [self._unit_checkboxes[name]]
            if name in self._unit_form_boxes:
                self._unit_form_boxes[name].add_class("cadetgui-subsection")
                children.append(self._unit_form_boxes[name])
            box = W.VBox(children)
            box.add_class("cadetgui-subsection")
            unit_subsections.append(box)
            if name == "mixer":
                # Physical order: mixer, then the optional sample loop.
                unit_subsections.append(sample_loop_subsection)

        self._flow_path_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Units In Flow Path</div>"),
                W.HTML(
                    "<em>Uncheck a unit to remove it from the flow path -- e.g. to "
                    "characterize the system before adding a column.</em>",
                    layout=W.Layout(margin="0 0 4px 0"),
                ),
                *unit_subsections,
            ]
        )
        self._flow_path_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>System</div>"),
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
        self._rebuild()

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
        self, column_cls: Optional[type], binding_cls: Optional[type]
    ) -> None:
        """Externally driven column/binding *type* choice -- see class docstring."""
        self._column_cls = column_cls
        self._binding_cls = binding_cls
        if not self._suspend_rebuild:
            self._rebuild()

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn(self.flow_sheet)

    def _on_change(self, change: dict) -> None:
        if change.get("name") not in ("value", "selected_index"):
            return
        self._apply_loop_field_visibility()
        if self._suspend_rebuild:
            return
        self._rebuild()

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
            self._sample_loop_checkbox.value = state.include_sample_loop
            self._loop_volume_field.value = state.sample_loop_volume
            self._loop_diameter_auto_checkbox.value = state.sample_loop_diameter_auto
            self._loop_diameter_field.value = state.sample_loop_diameter
            for name, checkbox in self._unit_checkboxes.items():
                checkbox.value = name not in state.bypass_units
            self._unit_values = {k: dict(v) for k, v in state.unit_values.items()}
        finally:
            self._suspend_rebuild = False

        self._apply_loop_field_visibility()
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
