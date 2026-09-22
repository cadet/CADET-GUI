from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import BINDING_MODELS, BYPASSABLE_UNITS, COLUMN_MODELS
from ...configuration_store import InstrumentState
from .._chrome import style_tag
from ..elements import ChoiceField, ComponentListField, FloatField

__all__ = ["InstrumentWidget"]


def _key_for_value(registry: Dict[str, Any], value: Any) -> Optional[str]:
    """Reverse-lookup a registry's human label for one of its values."""
    return next((k for k, v in registry.items() if v == value), None)


# Narrow, deliberate scope: mixer/tubing dead-volume geometry has no parameter
# form in this pass (unlike column/binding, which ConfigurationWidget still
# renders) -- seeded here with small, non-degenerate placeholder values so a
# fresh instrument is immediately simulatable. Real per-unit editing is future
# scope (REQUIREMENTS.md's "numerics/discretization exposure" item).
_TUBING_DIAMETER = 0.5e-3
_TUBING_LENGTH = 0.1
_TUBING_AXIAL_DISPERSION = 1e-7
_MIXER_VOLUME = 1e-6


def _seed_dead_volume_geometry(flow_sheet: LCFlowSheet, bypass: List[str]) -> None:
    if "mixer" not in bypass:
        flow_sheet.mixer.init_liquid_volume = _MIXER_VOLUME
    for name in (
        "tubing_pre_injection", "tubing_pre_column", "tubing_post_column", "tubing_detectors",
    ):
        if name in flow_sheet:
            unit = flow_sheet[name]
            unit.diameter = _TUBING_DIAMETER
            unit.length = _TUBING_LENGTH
            unit.axial_dispersion = _TUBING_AXIAL_DISPERSION


class InstrumentWidget:
    """Pick a component system, column/binding model type, and LC-system topology.

    Owns exactly what `LCFlowSheet` takes: component system, sample loop,
    column/binding model *type* (not their parameter values -- that's
    `ConfigurationWidget`'s job once bound, via `flow_sheet.column`/
    `.column.binding_model`), and which units are part of the experiment
    (bypass units). Builds and exposes `.flow_sheet`, auto-committing on every
    valid change; `add_listener` fires with it on every successful build.
    """

    def __init__(
        self,
        *,
        columns: Optional[Dict[str, type]] = None,
        binding_registry: Optional[Dict[str, Optional[type]]] = None,
    ) -> None:
        self._columns = columns or COLUMN_MODELS
        self._binding_registry = binding_registry or BINDING_MODELS
        self._listeners: List[Callable[[Any], None]] = []
        self.flow_sheet: Optional[LCFlowSheet] = None
        # Set around apply_state()'s field writes so each one's own observer
        # doesn't trigger its own rebuild -- one rebuild for the whole
        # restored selection instead of one per field touched.
        self._suspend_rebuild = False

        self._components = ComponentListField(label="Components:")
        self._component_note = W.HTML(layout=W.Layout(display="none"))
        self._component_note.add_class("cadetgui-note")

        self._include_loop_checkbox = W.Checkbox(
            description="Include sample loop", value=True, indent=False
        )
        self._loop_volume_field = FloatField(
            label="Sample loop volume", value=50e-9, units="m^3",
        )
        self._loop_diameter_auto_checkbox = W.Checkbox(
            description="Auto-derive diameter from volume", value=True, indent=False
        )
        self._loop_diameter_field = FloatField(
            label="Sample loop diameter", value=0.75e-3, units="m",
        )

        self._column_picker = ChoiceField(
            label="Column Model:", options=list(self._columns.items()),
            value=self._columns.get("Lumped Rate Model Without Pores (LRM)"),
        )
        self._binding_picker = ChoiceField(
            label="Binding Model:", options=list(self._binding_registry.items()),
            value=self._binding_registry.get("Linear"),
        )

        self._bypass_checkboxes: Dict[str, W.Checkbox] = {
            name: W.Checkbox(
                description=name.replace("_", " ").capitalize(), value=False, indent=False
            )
            for name in BYPASSABLE_UNITS
        }

        self.status = W.HTML("<em>Select a column and binding model.</em>")
        self.status.add_class("cadetgui-status")

        loop_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Sample Loop</div>"),
                self._include_loop_checkbox,
                self._loop_volume_field,
                self._loop_diameter_auto_checkbox,
                self._loop_diameter_field,
            ]
        )
        loop_section.add_class("cadetgui-section")

        model_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Column / Binding Model</div>"),
                self._column_picker,
                self._binding_picker,
            ]
        )
        model_section.add_class("cadetgui-section")

        bypass_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Units In Flow Path</div>"),
                W.HTML(
                    "<em>Uncheck a unit to exclude it -- e.g. to characterize the "
                    "system before adding a column.</em>",
                    layout=W.Layout(margin="0 0 4px 0"),
                ),
                *self._bypass_checkboxes.values(),
            ]
        )
        bypass_section.add_class("cadetgui-section")

        components_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Component System</div>"),
                self._components,
                self._component_note,
            ]
        )
        components_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Instrument</div>"),
                components_section,
                loop_section,
                model_section,
                bypass_section,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._components.observe(self._on_change, names="value")
        self._include_loop_checkbox.observe(self._on_change, names="value")
        self._loop_volume_field.observe(self._on_change, names="value")
        self._loop_diameter_auto_checkbox.observe(self._on_change, names="value")
        self._loop_diameter_field.observe(self._on_change, names="value")
        self._column_picker.observe(self._on_change, names="selected_index")
        self._binding_picker.observe(self._on_change, names="selected_index")
        for checkbox in self._bypass_checkboxes.values():
            checkbox.observe(self._on_change, names="value")

        self._apply_loop_field_visibility()
        self._rebuild()

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Register a callback fired with `.flow_sheet` on every successful build."""
        self._listeners.append(fn)

    @property
    def components(self) -> List[str]:
        """Current component names."""
        return list(self._components.value)

    @components.setter
    def components(self, names: List[str]) -> None:
        self._components.value = list(names)

    def set_min_components(self, minimum: int) -> None:
        """Raise/lower the component list's floor (e.g. for a gradient-needing template).

        Also drives an info note next to it and, via `min_components`, greys
        out the list's remove button once the row count hits the floor.
        """
        self._components.min_components = minimum
        if minimum > 1:
            self._component_note.value = (
                "The process template you selected does not allow less than"
                f" {minimum} components."
            )
            self._component_note.layout.display = ""
        else:
            self._component_note.layout.display = "none"

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
        """Capture the current selection as the hashed save/import payload."""
        column_key = _key_for_value(self._columns, self._column_picker.value)
        binding_key = _key_for_value(self._binding_registry, self._binding_picker.value)
        if column_key is None or binding_key is None:
            raise RuntimeError("Current column/binding selection isn't in a known registry.")
        return InstrumentState(
            components=list(self._components.value),
            column_key=column_key,
            binding_key=binding_key,
            include_sample_loop=bool(self._include_loop_checkbox.value),
            sample_loop_volume=float(self._loop_volume_field.value),
            sample_loop_diameter_auto=bool(self._loop_diameter_auto_checkbox.value),
            sample_loop_diameter=float(self._loop_diameter_field.value),
            bypass_units=self.bypass_units(),
        )

    def apply_state(self, state: InstrumentState) -> None:
        """Reconstruct pickers/fields from a saved InstrumentState."""
        if state.column_key not in self._columns:
            raise ValueError(f"Unknown column model {state.column_key!r}.")
        if state.binding_key not in self._binding_registry:
            raise ValueError(f"Unknown binding model {state.binding_key!r}.")

        self._suspend_rebuild = True
        try:
            self._components.value = list(state.components)
            self._column_picker.value = self._columns[state.column_key]
            self._binding_picker.value = self._binding_registry[state.binding_key]
            self._include_loop_checkbox.value = state.include_sample_loop
            self._loop_volume_field.value = state.sample_loop_volume
            self._loop_diameter_auto_checkbox.value = state.sample_loop_diameter_auto
            self._loop_diameter_field.value = state.sample_loop_diameter
            for name, checkbox in self._bypass_checkboxes.items():
                checkbox.value = name in state.bypass_units
        finally:
            self._suspend_rebuild = False

        self._apply_loop_field_visibility()
        self._rebuild()

    def _apply_loop_field_visibility(self) -> None:
        include_loop = self._include_loop_checkbox.value
        self._loop_volume_field.layout.display = "" if include_loop else "none"
        self._loop_diameter_auto_checkbox.layout.display = "" if include_loop else "none"
        auto = self._loop_diameter_auto_checkbox.value
        self._loop_diameter_field.layout.display = "" if (include_loop and not auto) else "none"

    def bypass_units(self) -> List[str]:
        """Currently-checked bypass unit names."""
        return [name for name, cb in self._bypass_checkboxes.items() if cb.value]

    def _rebuild(self) -> None:
        try:
            cs = ComponentSystem(list(self._components.value))
            bypass = self.bypass_units()
            include_loop = bool(self._include_loop_checkbox.value)
            loop_volume = float(self._loop_volume_field.value) if include_loop else None
            loop_diameter = None
            if include_loop and not self._loop_diameter_auto_checkbox.value:
                loop_diameter = float(self._loop_diameter_field.value)
            column_cls = None if "column" in bypass else self._column_picker.value
            binding_cls = self._binding_picker.value

            flow_sheet = LCFlowSheet(
                cs,
                sample_loop_volume=loop_volume,
                sample_loop_diameter=loop_diameter,
                ColumnModel=column_cls,
                BindingModel=binding_cls,
                bypass_units=bypass or None,
            )
            _seed_dead_volume_geometry(flow_sheet, bypass)
        except Exception as exc:  # noqa: BLE001
            self.status.value = f"<span style='color:#b00020'>{exc}</span>"
            return

        self.flow_sheet = flow_sheet
        self.status.value = "<em>Instrument built.</em>"
        self._notify()

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
