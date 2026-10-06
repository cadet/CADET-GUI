"""The setup form of a characterization step: step type, measurements, variables, optimizer."""

from __future__ import annotations

import html
import inspect
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ... import process_builder
from ...cadetprocessadapter import UNIT_LABELS
from ...characterization.comparison import Comparison
from ...characterization.guide import (
    CHAIN_BY_ID,
    EXPERIMENT_TYPES,
    ChainStepGuide,
    guide_for_step,
    option_help,
    option_label,
    parameter_label,
    starting_values,
    step_summary,
    step_type_help,
)
from ...characterization.runner import (
    DEFAULT_OPTIMIZER,
    StepSetup,
    default_optimizer,
    default_optimizer_knobs,
    estimated_simulations,
    fitted_variables,
)
from ...characterization.stages import STAGES, VariableDef, describe_stage
from ...characterization.study import Study
from ...optimizer_runner import OPTIMIZERS
from .._help import term_html
from .._status import status_html
from ..elements import BoolField, ChoiceField
from ._measurement_common import measurement_caption

MULTI_OBJECTIVE = DEFAULT_OPTIMIZER


def _knob_tooltip(is_population_based: bool) -> str:
    text = "Pre-filled from the number of fitted variables until you change it."
    if is_population_based:
        text += " 0 lets CADET-Process size it (large: can take hours)."
    return text


_VARIABLES_HELP = (
    "<div class='cadetgui-note'>"
    "<b>Fit</b> ticked: the optimizer searches this parameter between its lower and upper "
    "bound, starting from its current value, and the accepted candidate's value is written "
    "to the parameter store. Unticked, the parameter is <b>fixed</b>: it keeps its current "
    "value (from an earlier step, the starting values or the process setup) and this step "
    "does not change it. Keep a parameter fixed when your measurements cannot tell it "
    "apart from another one, e.g. characteristic charge and equilibrium constant from only "
    "a few similar gradients. "
    "<b>Dependent</b> variables are computed from the fitted ones and have no bounds."
    "</div>"
)

_FIT_TOOLTIP = (
    "Ticked: the optimizer fits this parameter between its bounds. Unticked: it is kept "
    "fixed at its current value."
)


def _unit_html(latex: str) -> str:
    """Render a CADET-Process LaTeX unit (fractions, powers, subscripts) as HTML."""
    if not latex:
        return ""
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", latex)
    text = re.sub(r"\^\{([^{}]*)\}", r"<sup>\1</sup>", text)
    text = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", text)
    text = text.replace("\\cdot", "·").replace(" ", "")

    def fraction(match: "re.Match[str]") -> str:
        numerator, denominator = match.group(1), match.group(2)
        if "·" in denominator:
            denominator = f"({denominator})"
        return f"{numerator}/{denominator}"

    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", fraction, text)
    return text.replace("{", "").replace("}", "").replace("\\", "")


def _is_bool(param: inspect.Parameter) -> bool:
    return param.annotation in (bool, "bool") or isinstance(param.default, bool)


def _does_not_fit_html(comparison: Comparison) -> str:
    experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
    if experiment is None:
        reason = "it has no experiment type"
    else:
        feeds = CHAIN_BY_ID.get(experiment.step_id)
        reason = f"{experiment.label} feeds {feeds.title if feeds else experiment.step_id}"
    return status_html(
        "warn", f"Does not fit this step ({reason}). Untick to remove it from the step."
    )


def _tubing_units(comparison: Comparison) -> list[str]:
    check = process_builder.check_recipe(comparison.recipe, comparison.overrides)
    return [u for u in check.units if u.startswith("tubing_")]


class _StepSetupForm:
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
        self._variables: List[VariableDef] = []

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

        self._comparison_rows = W.VBox()
        self._comparison_boxes: Dict[str, W.Checkbox] = {}
        self._comparison_note = W.HTML()
        self._no_fitting = W.HTML()
        self._btn_add_measurement = W.Button(
            description="Add measurement for this step", icon="upload",
            button_style="primary", layout=W.Layout(width="auto", display="none"),
        )
        self._btn_add_measurement.on_click(lambda _b: self._add_measurement_clicked())
        self._fitting: set[str] = set()
        self._excluded: Optional[set[str]] = None
        self._rows_guide: Optional[str] = None

        self._variables_box = W.VBox()
        self._bound_fields: Dict[str, tuple[W.FloatText, W.FloatText]] = {}
        self._fit_boxes: Dict[str, W.Checkbox] = {}
        self._current_cells: Dict[str, W.HTML] = {}

        self.requires = W.SelectMultiple(
            description="Requires:", layout=W.Layout(width="100%", height="110px")
        )
        self._require_paths: List[str] = []
        self._provides: List[str] = []
        self.provides = W.HTML()
        self._chain_line = W.HTML()
        self._chain_box = W.VBox([
            W.HTML("<small>Values this step needs from earlier steps, and what it determines."
                   "</small>"),
            self.requires,
            self.provides,
        ])

        self.optimizer = ChoiceField(
            label="Optimizer:", options=[(name, name) for name in OPTIMIZERS]
        )
        self.optimizer.value = MULTI_OBJECTIVE
        self._estimate = W.HTML()
        self._knob_fields: Dict[str, List[W.IntText]] = {
            name: [
                W.IntText(
                    value=k.default, description=k.label,
                    tooltip=_knob_tooltip(spec.is_population_based),
                )
                for k in spec.knobs
            ]
            for name, spec in OPTIMIZERS.items()
        }
        self._edited_knobs: set[tuple[str, str]] = set()
        self._knob_boxes = {
            name: W.HBox(fields, layout=W.Layout(flex_flow="row wrap"))
            for name, fields in self._knob_fields.items()
        }

        self.name.observe(self._edited, names="value")
        self.stage.observe(self._on_stage_change, names="selected_index")
        self.requires.observe(self._edited, names="value")
        self.optimizer.observe(self._on_optimizer_change, names="selected_index")
        for name, spec in OPTIMIZERS.items():
            for knob, knob_field in zip(spec.knobs, self._knob_fields[name]):
                knob_field.observe(
                    lambda _c, key=(name, knob.attr): self._on_knob_edit(key), names="value"
                )

        def section(title: str, *children: W.Widget) -> W.VBox:
            box = W.VBox([W.HTML(f"<div class='cadetgui-section-title'>{title}</div>"), *children])
            box.add_class("cadetgui-subsection")
            return box

        self.root = W.VBox([
            self.name,
            self.summary,
            self._chain_line,
            self._plain_slot,
            self.advanced,
            section(
                f"{term_html('measurement', 'Measurements')} (one objective each)",
                self._comparison_note,
                self._comparison_rows,
                W.HBox(
                    [self._no_fitting, self._btn_add_measurement],
                    layout=W.Layout(align_items="center", flex_flow="row wrap"),
                ),
            ),
            section("Variables", self._variables_box),
            section(
                "Optimizer",
                W.HBox(
                    [self.optimizer, *self._knob_boxes.values()],
                    layout=W.Layout(flex_flow="row wrap"),
                ),
                self._estimate,
            ),
        ])

    def _edited(self, _change: Any = None) -> None:
        if not self._syncing:
            self._on_change()

    def _on_knob_edit(self, key: tuple[str, str]) -> None:
        if self._syncing:
            return
        self._edited_knobs.add(key)
        self._update_estimate()
        self._on_change()

    def _on_fit_toggle(self, _change: Any) -> None:
        if self._syncing:
            return
        self._prefill_knobs()
        self._on_change()

    def _n_fitted(self) -> int:
        return len(fitted_variables(self._variables, self._frozen()))

    def _prefill_knobs(self) -> None:
        """Set every knob the user has not edited to its size for the fitted variables."""
        syncing, self._syncing = self._syncing, True
        try:
            n = self._n_fitted()
            for name, spec in OPTIMIZERS.items():
                sized = default_optimizer_knobs(name, n)
                for knob, knob_field in zip(spec.knobs, self._knob_fields[name]):
                    if (name, knob.attr) not in self._edited_knobs:
                        knob_field.value = sized[knob.attr]
        finally:
            self._syncing = syncing
        self._update_estimate()

    def _update_estimate(self) -> None:
        n_comparisons = len(self.selected_names())
        settings = self.optimizer_settings()
        count = estimated_simulations(settings, n_comparisons)
        measurements = f"{n_comparisons} measurement{'s' if n_comparisons != 1 else ''}"
        if settings["name"] == MULTI_OBJECTIVE and count is None:
            text = (
                "Population size or generations 0: CADET-Process sizes the run itself, "
                "which can take hours."
            )
        elif settings["name"] == MULTI_OBJECTIVE:
            knobs = settings["knobs"]
            text = (
                f"≈ {count:,} simulations ({knobs['pop_size']} × {knobs['n_max_gen']} "
                f"generations × {measurements})."
            )
        elif count is not None:
            text = (
                f"≈ {count:,} simulations (max iterations × {measurements}; approximate, "
                "scipy's evaluations per iteration vary)."
            )
        else:
            text = ""
        self._estimate.value = f"<small>{html.escape(text)}</small>" if text else ""

    def _on_stage_change(self, _change: Any) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self._rebuild_options({})
            self._rebuild_variables({}, ())
        finally:
            self._syncing = False
        self._prefill_knobs()
        self._on_change()

    def _on_option_change(self, _change: Any) -> None:
        if self._syncing:
            return
        bounds, frozen = self._bounds(), self._frozen()
        self._syncing = True
        try:
            self._rebuild_variables(bounds, frozen)
        finally:
            self._syncing = False
        self._prefill_knobs()
        self._on_change()

    def _on_comparison_toggle(self, change: Any) -> None:
        if self._syncing:
            return
        name = next(n for n, box in self._comparison_boxes.items() if box is change["owner"])
        if name in self._fitting:
            (self._excluded.discard if change["new"] else self._excluded.add)(name)
        bounds, frozen = self._bounds(), self._frozen()
        self._syncing = True
        try:
            self._rebuild_options(self._options())
            self._rebuild_variables(bounds, frozen)
            self._sync_optimizers()
        finally:
            self._syncing = False
        self._prefill_knobs()
        self._on_change()

    def _on_optimizer_change(self, _change: Any) -> None:
        selected = self.optimizer.value
        for name, box in self._knob_boxes.items():
            box.layout.display = "" if name == selected else "none"
        self._update_estimate()
        self._edited()

    def set_setup(self, setup: StepSetup) -> None:
        """Show `setup` in the controls without firing `on_change`."""
        self._syncing = True
        try:
            self.name.value = setup.name
            self.stage.value = setup.stage
            self._excluded = None if setup.excluded is None else set(setup.excluded)
            self.refresh_comparisons([c.name for c in setup.comparisons])
            self._rebuild_options(setup.options)
            self._rebuild_variables(setup.bounds, setup.frozen)
            self.refresh_requires(setup)
            self.requires.value = tuple(p for p in setup.requires if p in self._require_paths)
            self._set_optimizer(setup.optimizer)
            self._prefill_knobs()
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
            self.show_chain(self._provides)
        guide = self.guide()
        if (guide.id if guide else None) != self._rows_guide:
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
        if not self._current_cells:
            return
        try:
            values = starting_values(self._study, self._layout_setup(), self._variables)
        except Exception:  # noqa: BLE001 -- unbuildable recipes are reported elsewhere
            values = {}
        for name, cell in self._current_cells.items():
            start = values.get(name)
            if start is None:
                text = "—"
            else:
                unit = _unit_html(start.unit)
                text = (
                    f"{html.escape(start.text)}{' ' + unit if unit else ''}"
                    f"<br><small>{html.escape(start.source)}</small>"
                )
            if cell.value != text:
                cell.value = text

    def _set_optimizer(self, optimizer: dict) -> None:
        """Show `optimizer`; its knobs that differ from the sized defaults count as edited."""
        name = optimizer.get("name", MULTI_OBJECTIVE)
        sized = default_optimizer_knobs(name, self._n_fitted())
        self._edited_knobs = set()
        for knob, knob_field in zip(OPTIMIZERS[name].knobs, self._knob_fields[name]):
            knob_field.value = int(optimizer.get("knobs", {}).get(knob.attr, knob.default))
            if knob_field.value != sized[knob.attr]:
                self._edited_knobs.add((name, knob.attr))
        self.optimizer.value = name
        self._sync_optimizers()

    def refresh_comparisons(
        self, selected: Optional[List[str]] = None, *, auto_include: bool = False
    ) -> List[str]:
        """Rebuild the measurement rows from the study, keeping (or setting) the selection.

        A chain step lists only the measurements whose experiment type feeds it, plus
        selected ones that do not fit (with a warning); a custom step lists all. Fitting
        measurements unselected when a chain step is first shown without recorded
        exclusions, or when the user switches it to another chain step, count as left out.
        With `auto_include`, fitting measurements not left out are selected; returns them.
        """
        if selected is None:
            selected = self.selected_names()
        guide = self.guide()
        guide_id = guide.id if guide is not None else None
        added: List[str] = []
        if guide is None:
            shown = list(self._study.comparisons)
            fitting_names: set[str] = {c.name for c in shown}
        else:
            fitting = [
                c for c in self._study.comparisons if c.experiment_type in guide.experiment_types
            ]
            fitting_names = {c.name for c in fitting}
            if self._excluded is None or (guide_id != self._rows_guide and not self._syncing):
                self._excluded = (self._excluded or set()) | (fitting_names - set(selected))
            if auto_include:
                added = [
                    c.name for c in fitting
                    if c.name not in self._excluded and c.name not in selected
                ]
                selected = [*selected, *added]
            shown = [
                c for c in self._study.comparisons
                if c.name in fitting_names or c.name in selected
            ]
        self._rows_guide = guide_id
        self._fitting = fitting_names if guide is not None else set()

        syncing, self._syncing = self._syncing, True
        rows, self._comparison_boxes = [], {}
        for comparison in shown:
            box = W.Checkbox(
                value=comparison.name in selected, indent=False,
                layout=W.Layout(width="auto"), disabled=self.stage.disabled,
            )
            box.observe(self._on_comparison_toggle, names="value")
            self._comparison_boxes[comparison.name] = box
            problems = self._study.measurement_problems(comparison)
            chip = (
                status_html("warn", f"{len(problems)} problem(s): " + " ".join(problems))
                if problems else status_html("ok", "ready")
            )
            detail = html.escape(measurement_caption(comparison))
            children = [
                box,
                W.HTML(f"<b>{html.escape(comparison.name)}</b> <small>{detail}</small>"),
                W.HTML(chip),
            ]
            if comparison.name not in fitting_names:
                children.append(W.HTML(_does_not_fit_html(comparison)))
            rows.append(W.HBox(children, layout=W.Layout(align_items="center")))
        if not rows and guide is None:
            rows = [W.HTML("<em>No measurements in this study yet.</em>")]
        self._comparison_rows.children = rows
        self._syncing = syncing

        if guide is None:
            self._comparison_note.value = ""
            self._no_fitting.value = ""
        else:
            self._comparison_note.value = (
                "<small>Measurements whose experiment type feeds this step. All are "
                "included; untick one to leave it out (e.g. a bad replicate). New ones "
                "are included when you add them.</small>"
            )
            labels = ", ".join(EXPERIMENT_TYPES[t].label for t in guide.experiment_types)
            self._no_fitting.value = "" if fitting_names else status_html(
                "warn", f"No measurement fits this step yet. It needs: {labels}."
            )
        show_add = guide is not None and not fitting_names and self._on_add_measurement
        self._btn_add_measurement.layout.display = "" if show_add else "none"
        return added

    def refresh_requires(self, setup: StepSetup) -> None:
        """Offer every declared path and every other step's outputs as requirements."""
        paths = set(self._study.initial_store.specs) | set(self._study.initial_store.entries)
        for step in self._study.steps:
            if step.name == setup.name:
                continue
            try:
                paths.update(step.provides)
            except ValueError:
                pass
        paths.update(setup.requires)
        options = sorted(paths)
        if self._require_paths != options:
            syncing, self._syncing = self._syncing, True
            kept = tuple(p for p in self.requires.value if p in options)
            self._require_paths = options
            self.requires.options = [(parameter_label(p), p) for p in options]
            self.requires.value = kept
            self._syncing = syncing

    def show_chain(self, provides: List[str]) -> None:
        """Show what the step uses from earlier steps and what it determines."""
        self._provides = list(provides)

        def names(paths: Any) -> str:
            return ", ".join(html.escape(parameter_label(p)) for p in paths) or "nothing"

        self.provides.value = f"<small>Determines: {names(provides)}</small>"
        self._chain_line.value = (
            f"<small>Uses from earlier steps: {names(self.requires.value)} · "
            f"Determines: {names(provides)}</small>"
        ) if self.guided else ""

    def selected_names(self) -> List[str]:
        return [name for name, box in self._comparison_boxes.items() if box.value]

    def _selected(self) -> List[Comparison]:
        by_name = {c.name: c for c in self._study.comparisons}
        return [by_name[n] for n in self.selected_names() if n in by_name]

    def problems_of_selected(self) -> Dict[str, List[str]]:
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
        self._bound_fields, self._fit_boxes, self._current_cells = {}, {}, {}
        try:
            self._variables = describe_stage(self.stage.value, **self._options())
        except ValueError as exc:
            self._variables = []
            self._variables_box.children = [W.HTML(status_html("warn", str(exc)))]
            return

        header = [
            term_html("fixed variable", "Fit"),
            "Variable", "Current value", "Parameter path", "Lower bound", "Upper bound",
        ]
        cells: List[W.Widget] = [W.HTML(f"<b>{h}</b>") for h in header]
        for var in self._variables:
            path = html.escape(var.parameter_path or "(helper)")
            current = W.HTML("—")
            if var.parameter_path is not None:
                self._current_cells[var.name] = current
            if var.is_dependent:
                cells += [
                    W.HTML("<em>dependent</em>"), W.Label(var.name), current,
                    W.HTML(f"<code>{path}</code>"), W.Label("—"), W.Label("—"),
                ]
                continue
            lb, ub = bounds.get(var.name, (var.lb, var.ub))
            lb_field = W.FloatText(value=float(lb), layout=W.Layout(width="120px"))
            ub_field = W.FloatText(value=float(ub), layout=W.Layout(width="120px"))
            fit = W.Checkbox(
                value=var.name not in frozen, description="Fit", indent=False,
                tooltip=_FIT_TOOLTIP, layout=W.Layout(width="auto"),
            )
            for control in (lb_field, ub_field):
                control.observe(self._edited, names="value")
            fit.observe(self._on_fit_toggle, names="value")
            self._bound_fields[var.name] = (lb_field, ub_field)
            self._fit_boxes[var.name] = fit
            cells += [
                fit, W.Label(var.name), current, W.HTML(f"<code>{path}</code>"),
                lb_field, ub_field,
            ]
        self._variables_box.children = [
            W.HTML(_VARIABLES_HELP),
            W.GridBox(cells, layout=W.Layout(
                grid_template_columns="70px 200px 200px 1fr 130px 130px", align_items="center",
            )),
        ]
        self.refresh_current_values()

    def _bounds(self) -> dict:
        defaults = {v.name: (v.lb, v.ub) for v in self._variables}
        bounds = {}
        for name, (lb, ub) in self._bound_fields.items():
            pair = (float(lb.value), float(ub.value))
            if pair != defaults.get(name):
                bounds[name] = pair
        return bounds

    def _frozen(self) -> tuple:
        return tuple(n for n, box in self._fit_boxes.items() if not box.value)

    def _sync_optimizers(self) -> None:
        n = len(self.selected_names())
        allowed = list(OPTIMIZERS) if n == 1 else [MULTI_OBJECTIVE]
        current = self.optimizer.value
        self.optimizer.set_options([(name, name) for name in allowed])
        self.optimizer.value = current if current in allowed else MULTI_OBJECTIVE
        self._on_optimizer_change(None)

    def get_setup(self) -> StepSetup:
        """Return the setup the controls describe; comparisons resolve against the study."""
        return StepSetup(
            name=self.name.value.strip(),
            stage=self.stage.value,
            options=self._options(),
            comparisons=self._selected(),
            bounds=self._bounds(),
            frozen=self._frozen(),
            requires=tuple(self.requires.value),
            optimizer=self.optimizer_settings(),
            excluded=None if self._excluded is None else tuple(
                c.name for c in self._study.comparisons if c.name in self._excluded
            ),
        )

    def optimizer_settings(self) -> dict:
        """Return the chosen optimizer as `StepSetup.optimizer`."""
        name = self.optimizer.value
        knobs = OPTIMIZERS[name].knobs
        return default_optimizer(
            name, **{k.attr: int(f.value) for k, f in zip(knobs, self._knob_fields[name])}
        )

    def set_locked(self, locked: bool) -> None:
        """Make every control read-only (or editable again)."""
        controls: List[Any] = [self.name, self.stage, self.requires, self.optimizer]
        controls += list(self._option_fields.values()) + list(self._comparison_boxes.values())
        controls += [f for pair in self._bound_fields.values() for f in pair]
        controls += list(self._fit_boxes.values())
        controls += [f for fields in self._knob_fields.values() for f in fields]
        for control in controls:
            control.disabled = locked
