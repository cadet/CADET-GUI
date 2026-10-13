"""The setup form of a characterization step: step type, measurements, variables, optimizer."""

from __future__ import annotations

import html
import inspect
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import (
    ChainStepGuide,
    guide_for_step,
    option_help,
    option_label,
    step_summary,
    step_type_help,
)
from ....characterization.runner import StepSetup
from ....characterization.stages import STAGES
from ....characterization.study import Study
from ....instrument import process_builder
from ....instrument.system import UNIT_LABELS
from ...elements import BoolField, ChoiceField
from ...ui.layout import section_title
from ..help import term_html
from .chain_links import ChainLinks
from .measurement_picker import MeasurementPicker
from .optimizer_settings import OptimizerSettings
from .variables_table import VariablesTable


def _is_bool(param: inspect.Parameter) -> bool:
    return param.annotation in (bool, "bool") or isinstance(param.default, bool)


def _tubing_units(comparison: Comparison) -> list[str]:
    check = process_builder.check_recipe(comparison.recipe, comparison.overrides)
    return [u for u in check.units if u.startswith("tubing_")]


def _subsection(title: str, *children: W.Widget) -> W.VBox:
    box = W.VBox([section_title(title), *children])
    box.add_class("cadetgui-subsection")
    return box


class StepSetupForm:
    """Controls for one `StepSetup` plus the optimizer choice; `on_change()` fires on user edits."""

    def __init__(
        self,
        study: Study,
        on_change: Callable[[], None],
        on_add_measurement: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._study = study
        self._on_change = on_change
        self._on_add_measurement = on_add_measurement
        self._syncing = False

        self.name = W.Text(description="Step name:", continuous_update=False)
        self.stage = ChoiceField(
            label="Step type:", options=[(s.label, s.id) for s in STAGES.values()]
        )
        self._stage_help = W.HTML()
        self._options_box = W.VBox()
        self._option_fields: Dict[str, Any] = {}
        self.summary = W.HTML()
        self._stage_controls = W.VBox([self.stage, self._stage_help, self._options_box])
        self._plain_slot = W.VBox()
        self._advanced_body = W.VBox()
        self.advanced = W.Accordion([self._advanced_body])
        self.advanced.set_title(0, "Advanced: step type and options")
        self.advanced.selected_index = None
        self.advanced.layout.display = "none"
        self.guided = False

        self.measurements = MeasurementPicker(
            study, self._on_comparison_toggle,
            on_add=self._add_measurement_clicked if on_add_measurement is not None else None,
        )
        self._comparison_rows = self.measurements.rows
        self._comparison_note = self.measurements.note
        self._no_fitting = self.measurements.no_fitting
        self._btn_add_measurement = self.measurements.btn_add

        self.variables_table = VariablesTable(study, self._edited, self._on_fit_toggle)
        self._variables_box = self.variables_table.box

        self.chain = ChainLinks(study, self._edited)
        self.requires = self.chain.requires
        self.provides = self.chain.provides
        self._chain_line = self.chain.line
        self._chain_box = self.chain.box

        self.optimizer_part = OptimizerSettings(
            self.variables_table.n_fitted, lambda: len(self.selected_names()), self._edited
        )
        self.optimizer = self.optimizer_part.optimizer
        self._estimate = self.optimizer_part.estimate
        self._knob_fields = self.optimizer_part.knob_fields

        self.name.observe(self._edited, names="value")
        self.stage.observe(self._on_stage_change, names="selected_index")

        self.root = W.VBox([
            self.name,
            self.summary,
            self._chain_line,
            self._plain_slot,
            self.advanced,
            _subsection(
                f"{term_html('measurement', 'Measurements')} (one objective each)",
                self._comparison_note,
                self._comparison_rows,
                W.HBox(
                    [self._no_fitting, self._btn_add_measurement],
                    layout=W.Layout(align_items="center", flex_flow="row wrap"),
                ),
            ),
            _subsection("Variables", self._variables_box),
            _subsection("Optimizer", self.optimizer_part.controls, self._estimate),
        ])

    @property
    def _comparison_boxes(self) -> Dict[str, W.Checkbox]:
        return self.measurements.boxes

    @property
    def _bound_fields(self) -> Dict[str, tuple[W.FloatText, W.FloatText]]:
        return self.variables_table.bound_fields

    @property
    def _fit_boxes(self) -> Dict[str, W.Checkbox]:
        return self.variables_table.fit_boxes

    @property
    def _current_cells(self) -> Dict[str, W.HTML]:
        return self.variables_table.current_cells

    def _edited(self, _change: Any = None) -> None:
        if not self._syncing:
            self._on_change()

    def _on_fit_toggle(self, _change: Any) -> None:
        if self._syncing:
            return
        self.optimizer_part.prefill()
        self._on_change()

    def _on_stage_change(self, _change: Any) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self._rebuild_options({})
            self._rebuild_variables({}, ())
        finally:
            self._syncing = False
        self.optimizer_part.prefill()
        self._on_change()

    def _on_option_change(self, _change: Any) -> None:
        if self._syncing:
            return
        bounds, frozen = self.variables_table.bounds(), self.variables_table.frozen()
        self._syncing = True
        try:
            self._rebuild_variables(bounds, frozen)
        finally:
            self._syncing = False
        self.optimizer_part.prefill()
        self._on_change()

    def _on_comparison_toggle(self) -> None:
        if self._syncing:
            return
        bounds, frozen = self.variables_table.bounds(), self.variables_table.frozen()
        self._syncing = True
        try:
            self._rebuild_options(self._options())
            self._rebuild_variables(bounds, frozen)
            self.optimizer_part.sync_choices()
        finally:
            self._syncing = False
        self.optimizer_part.prefill()
        self._on_change()

    def set_setup(self, setup: StepSetup) -> None:
        """Show `setup` in the controls without firing `on_change`."""
        self._syncing = True
        try:
            self.name.value = setup.name
            self.stage.value = setup.stage
            self.measurements.excluded = None if setup.excluded is None else set(setup.excluded)
            self.refresh_comparisons([c.name for c in setup.comparisons])
            self._rebuild_options(setup.options)
            self._rebuild_variables(setup.bounds, setup.frozen)
            self.refresh_requires(setup)
            self.chain.set_required(setup.requires)
            self.optimizer_part.set_settings(setup.optimizer)
            self.optimizer_part.prefill()
        finally:
            self._syncing = False
        self.refresh_summary()

    def _layout_setup(self) -> SimpleNamespace:
        return SimpleNamespace(
            name=self.name.value.strip(), stage=self.stage.value, options=self._options(),
            comparisons=self._selected(),
        )

    def refresh_summary(self) -> None:
        """Show what the step fits; a chain step keeps its type and options under Advanced."""
        setup = self._layout_setup()
        help_text = step_type_help(self.stage.value)
        stage_help = f"<small>{html.escape(help_text)}</small>" if help_text else ""
        if self._stage_help.value != stage_help:
            self._stage_help.value = stage_help
        guided = guide_for_step(setup) is not None
        summary = f"<p><b>What this step fits:</b> {html.escape(step_summary(setup))}</p>"
        if self.summary.value != summary:
            self.summary.value = summary
        if guided != self.guided or not (
            self._plain_slot.children or self._advanced_body.children
        ):
            self.guided = guided
            self._plain_slot.children = () if guided else (self._stage_controls,)
            self._advanced_body.children = (self._stage_controls if guided else self._chain_box,)
            self.advanced.set_title(
                0, "Advanced: step type and options" if guided else "Advanced: chain links"
            )
            self.advanced.layout.display = ""
            self.show_chain(self.chain.provided)
        guide = self.guide()
        if (guide.id if guide else None) != self.measurements.rows_guide:
            self.refresh_comparisons()
        self.refresh_current_values()

    def guide(self) -> Optional[ChainStepGuide]:
        """Return the chain guide the step follows (by name, step type and options), if any."""
        return guide_for_step(SimpleNamespace(
            name=self.name.value.strip(), stage=self.stage.value, options=self._options(),
        ))

    def _add_measurement_clicked(self) -> None:
        guide = self.guide()
        if guide is not None and self._on_add_measurement is not None:
            self._on_add_measurement(guide.id)

    def refresh_current_values(self) -> None:
        """Fill the "Current value" column from the step's prior or the process setup."""
        if self.variables_table.current_cells:
            self.variables_table.refresh_current_values(self._layout_setup())

    def refresh_comparisons(
        self, selected: Optional[List[str]] = None, *, auto_include: bool = False
    ) -> List[str]:
        """Rebuild the measurement rows, keeping (or setting) the selection.

        See `MeasurementPicker.refresh`; returns the measurements `auto_include` selected.
        """
        return self.measurements.refresh(
            self.guide(), selected, auto_include=auto_include, syncing=self._syncing,
            disabled=self.stage.disabled,
        )

    def refresh_requires(self, setup: StepSetup) -> None:
        """Offer every declared path and every other step's outputs as requirements."""
        self.chain.refresh(setup)

    def show_chain(self, provides: List[str]) -> None:
        """Show what the step uses from earlier steps and what it determines."""
        self.chain.show(provides, self.guided)

    def selected_names(self) -> List[str]:
        """Return the names of the ticked measurements."""
        return self.measurements.selected_names()

    def _selected(self) -> List[Comparison]:
        return self.measurements.selected()

    def problems_of_selected(self) -> Dict[str, List[str]]:
        """Return the open problems of each ticked measurement that has any."""
        found = {c.name: self._study.measurement_problems(c) for c in self._selected()}
        return {name: problems for name, problems in found.items() if problems}

    def _rebuild_options(self, options: dict) -> None:
        stage = STAGES[self.stage.value]
        selected = self._selected()
        fields: Dict[str, Any] = {}
        for name, param in stage.options.items():
            current = options.get(name, param.default)
            if name == "tubing":
                units = [u for u in UNIT_LABELS if u.startswith("tubing_")]
                for comparison in selected:
                    present = _tubing_units(comparison)
                    units = [u for u in units if u in present]
                field = ChoiceField(
                    label=f"{option_label(name)}:", options=[(UNIT_LABELS[u], u) for u in units],
                    value=current if current in units else None,
                )
            elif name == "component_index":
                components = list(selected[0].recipe.components) if selected else []
                count = max(len(components), int(current or 0) + 1)
                labels = components + [str(i) for i in range(len(components), count)]
                field = ChoiceField(
                    label=f"{option_label(name)}:",
                    options=[(lab, i) for i, lab in enumerate(labels)],
                    value=int(current or 0),
                )
            elif _is_bool(param):
                field = BoolField(label=option_label(name), value=bool(current))
            else:
                field = W.Text(description=option_label(name), value=str(current or ""))
            field.observe(
                self._on_option_change,
                names="selected_index" if isinstance(field, ChoiceField) else "value",
            )
            fields[name] = field
        self._option_fields = fields
        self._options_box.children = [
            W.VBox([
                field,
                W.HTML(f"<small>{html.escape(option_help(stage.id, name))}</small>"),
            ])
            for name, field in fields.items()
        ]

    def _options(self) -> dict:
        options = {}
        for name, field in self._option_fields.items():
            if field.value is not None and field.value != "":
                options[name] = field.value
        return options

    def _rebuild_variables(self, bounds: dict, frozen: Any) -> None:
        self.variables_table.rebuild(self.stage.value, self._options(), bounds, frozen)
        self.refresh_current_values()

    def get_setup(self) -> StepSetup:
        """Return the setup the controls describe; comparisons resolve against the study."""
        return StepSetup(
            name=self.name.value.strip(),
            stage=self.stage.value,
            options=self._options(),
            comparisons=self._selected(),
            bounds=self.variables_table.bounds(),
            frozen=self.variables_table.frozen(),
            requires=tuple(self.requires.value),
            optimizer=self.optimizer_settings(),
            excluded=self.measurements.excluded_names(),
        )

    def optimizer_settings(self) -> dict:
        """Return the chosen optimizer as `StepSetup.optimizer`."""
        return self.optimizer_part.settings()

    def set_locked(self, locked: bool) -> None:
        """Make every control read-only (or editable again)."""
        for control in [self.name, self.stage, self.requires, *self._option_fields.values()]:
            control.disabled = locked
        self.measurements.set_locked(locked)
        self.variables_table.set_locked(locked)
        self.optimizer_part.set_locked(locked)
