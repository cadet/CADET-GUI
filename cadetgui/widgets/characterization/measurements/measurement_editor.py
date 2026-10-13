"""The Advanced editor of a measurement: every field of a comparison, in titled sections."""

from __future__ import annotations

import dataclasses
import html
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import EXPERIMENT_TYPES, role_fix
from ....characterization.study import Study
from ....instrument.process_builder import check_recipe
from ....instrument.templates import ML_PER_MIN
from ....io.configuration_store import ConfigurationState
from ....io.experimental_data import ExperimentalRun
from ...elements import BoolField, ChoiceField, TextField
from ...ui.layout import collapsible, note, row, section_title
from ..help import term_html
from .labels import (
    check_float,
    component_options,
    flow_rate_text,
    number_or_blank,
    optional_float,
    read_flow_rate,
)
from .recipe_overrides import RecipeOverrides
from .role_fix import RoleFixPrompt

__all__ = ["ADVANCED_TITLE", "METRICS", "MeasurementEditor"]

# CADET-Process difference metrics that `setup_comparators` builds from the name alone.
METRICS: Tuple[str, ...] = (
    "NRMSE", "RMSE", "SSE", "L1", "L2", "AbsoluteArea", "RelativeArea",
    "Shape", "ShapeFront", "PeakHeight", "PeakPosition",
)

ADVANCED_TITLE = (
    "Advanced: fine-tune how this measurement is compared — the defaults from its "
    "experiment type are usually right."
)


def _subsection(title: str, when: str, children: Sequence[W.Widget]) -> W.VBox:
    box = W.VBox([
        W.HTML(f"<div class='cadetgui-section-title'>{html.escape(title)}</div>"),
        note(f"<small>{html.escape(when)}</small>"),
        *children,
    ])
    box.add_class("cadetgui-subsection")
    return box


class MeasurementEditor:
    """Fields of one comparison under an Advanced accordion; fills them and reads a draft.

    `check_name` validates the name; `on_edit` is called when a field changes. The host
    observes `run`, `overrides.template` and `overrides.use_recipe` itself and guards
    `on_edit` while it fills the fields.
    """

    def __init__(
        self,
        study: Study,
        *,
        check_name: Callable[[str], Optional[str]],
        on_edit: Callable[..., None],
    ) -> None:
        self.study = study
        self._on_edit = on_edit
        self.recipe: Optional[ConfigurationState] = None
        self.runs: Dict[str, Optional[ExperimentalRun]] = {}
        self.component_fields: Dict[str, BoolField] = {}

        self.name = TextField(label="Name:", validate=check_name)
        self.probe = ChoiceField(label="Component:")
        self.role_fix = RoleFixPrompt()
        self.experiment_type = ChoiceField(
            label="Experiment type:",
            options=[("Not set", None), *((t.label, t.id) for t in EXPERIMENT_TYPES.values())],
        )
        self.run = ChoiceField(label="Data run:")
        self.channel = ChoiceField(label="Channel:")
        self.data_file = W.HTML()
        self.flow_rate = TextField(label="Run flow rate:", units="mL/min", validate=check_float)
        self.flow_rate_note = note()
        self.overrides = RecipeOverrides(on_edit)

        self.marker = ChoiceField(label="Injection marker:")
        self.injection_x = TextField(label="Injection at:", validate=check_float)
        self.baseline_start = TextField(label="Baseline from:", validate=check_float)
        self.baseline_end = TextField(label="to:", validate=check_float)
        self.normalization = ChoiceField(
            label="Normalization:", options=[("None", "none"), ("Area", "area")]
        )
        self.target_area = TextField(label="Target area:", validate=check_float)

        self.solution_path = ChoiceField(label="Observation point:")
        self.components_box = W.HBox(layout=W.Layout(flex_flow="row wrap"))
        self.metric = ChoiceField(label="Metric:", options=[(m, m) for m in METRICS])
        self.window_start = TextField(label="Compare from:", units="s", validate=check_float)
        self.window_end = TextField(label="to:", units="s", validate=check_float)

        for choice in (self.channel, self.marker, self.normalization,
                       self.solution_path, self.metric, self.experiment_type, self.probe):
            choice.observe(on_edit, names="selected_index")
        for text in (self.name, self.flow_rate, self.injection_x,
                     self.baseline_start, self.baseline_end, self.target_area,
                     self.window_start, self.window_end):
            text.observe(on_edit, names="value")

        overrides = self.overrides
        self.sections: Dict[str, W.VBox] = {
            title: _subsection(title, when, children)
            for title, when, children in (
                (
                    "Data and alignment",
                    "Change when the wrong run or detector channel is used, or the measured "
                    "trace is shifted in time against the simulation.",
                    [
                        row(self.run, self.channel, self.data_file),
                        row(self.flow_rate, self.flow_rate_note),
                        section_title(term_html("injection marker", "Injection marker")),
                        row(self.marker, self.injection_x),
                    ],
                ),
                (
                    "Baseline and scaling",
                    "Change when the measured baseline drifts or the trace needs another "
                    "scale, e.g. to match the injected amount.",
                    [
                        section_title(term_html("baseline window", "Baseline window")),
                        row(self.baseline_start, self.baseline_end),
                        section_title(term_html("normalization", "Normalization")),
                        row(self.normalization, self.target_area),
                    ],
                ),
                (
                    "Simulated signal",
                    "Change when the detector sits elsewhere in the flow path or another "
                    "component should be compared.",
                    [
                        section_title(term_html("observation point", "Observation point")
                                      + " (solution path) and component"),
                        row(self.solution_path, self.probe),
                        self.role_fix.root,
                        self.components_box,
                    ],
                ),
                (
                    "Comparison",
                    "Change to use another error measure, or to compare only part of the "
                    "run (e.g. leave out a noisy tail).",
                    [row(self.metric), row(self.window_start, self.window_end)],
                ),
                (
                    "Process",
                    "Change only if the run followed another method than its experiment "
                    "type assumes.",
                    [
                        row(overrides.template),
                        overrides.template_note,
                        section_title(
                            term_html("recipe", "Recipe") + " source and method overrides"
                        ),
                        row(overrides.source, overrides.use_recipe),
                        overrides.box,
                    ],
                ),
                (
                    "Name and type",
                    "Change to rename the measurement or give it another experiment type.",
                    [
                        row(self.name, self.experiment_type),
                        note("Changing the experiment type moves the measurement to another "
                             "step's group; it does not rebuild the recipe (add the run "
                             "again for that)."),
                    ],
                ),
            )
        }
        self.root = collapsible(ADVANCED_TITLE, W.VBox(list(self.sections.values())))

    def load(self, comparison: Comparison) -> None:
        """Fill every field from `comparison`; call `set_runs` first."""
        self.name.value = comparison.name
        self.name._run_validate()
        self.experiment_type.value = comparison.experiment_type
        self.fill_probe(comparison.experiment_type, comparison.probe)
        self.run.value = comparison.data_file
        self.flow_rate.value = flow_rate_text(comparison.flow_rate)
        baseline = comparison.baseline_window or (None, None)
        self.baseline_start.value = number_or_blank(baseline[0])
        self.baseline_end.value = number_or_blank(baseline[1])
        self.injection_x.value = number_or_blank(comparison.measured_injection)
        self.normalization.value = comparison.normalization.get("kind", "none")
        self.target_area.value = number_or_blank(comparison.normalization.get("target_area"))
        self.metric.set_options(
            [(m, m) for m in dict.fromkeys((*METRICS, comparison.metric))], keep_value=False
        )
        self.metric.value = comparison.metric
        self.window_start.value = number_or_blank(comparison.window[0])
        self.window_end.value = number_or_blank(comparison.window[1])
        self.load_run_dependents(comparison.run, comparison)
        self.load_recipe(comparison.recipe, comparison)

    def set_runs(self, runs: Dict[str, Optional[ExperimentalRun]]) -> None:
        """Offer `runs` (by data file) as the data runs."""
        self.runs = runs
        self.run.set_options([
            (f"{key} ({len(run.channels)} channels)" if run is not None else f"{key} (not loaded)",
             key)
            for key, run in runs.items()
        ])

    def fill_probe(self, type_id: Optional[str], probe: Optional[str]) -> None:
        """Offer the declared components whose role fits `type_id`; keep `probe` listed."""
        experiment_type = EXPERIMENT_TYPES.get(type_id or "")
        roles = experiment_type.probe_roles if experiment_type is not None else None
        options: List[Tuple[str, Optional[str]]] = [("None", None)]
        options += component_options(self.study, roles)
        if probe is not None and probe not in [v for _, v in options]:
            component = self.study.component(probe)
            text = f"{component.role}, does not fit" if component else "not declared"
            options.append((f"{probe} ({text})", probe))
        self.probe.set_options(options, keep_value=False)
        self.probe.value = probe
        text, target = role_fix(self.study, probe, experiment_type) if (
            probe and experiment_type is not None
        ) else ("", None)
        self.role_fix.show(probe, text, target)

    def load_run_dependents(
        self, run: Optional[ExperimentalRun], comparison: Comparison
    ) -> None:
        """Fill the channel, marker and data-file fields from `run` and `comparison`."""
        channels = list(run.channels) if run is not None else []
        if comparison.channel and comparison.channel not in channels:
            channels.append(comparison.channel)
        self.channel.set_options([(c, c) for c in channels], keep_value=False)
        self.channel.value = comparison.channel

        marker = comparison.injection_marker
        options: List[Tuple[str, Optional[str]]] = [("None / manual", None)]
        matched = False
        for x, text in run.markers if run is not None else ():
            value = text
            if marker is not None and not matched and text.startswith(marker):
                value, matched = marker, True
            options.append((f"{text} @ {x:g} {run.x_unit}", value))
        if marker is not None and not matched:
            options.append((f"{marker} (not in run)", marker))
        self.marker.set_options(options, keep_value=False)
        self.marker.value = marker

        x_unit = run.x_unit if run is not None else ""
        for field in (self.injection_x, self.baseline_start, self.baseline_end):
            field.units = x_unit
        file_note = f"file: {html.escape(comparison.data_file)}" if comparison.data_file else ""
        self.data_file.value = f"<span class='cadetgui-note'>{file_note}</span>"

    def load_recipe(self, recipe: ConfigurationState, comparison: Comparison) -> None:
        """Fill the recipe-dependent fields from `recipe` and `comparison`."""
        self.recipe = recipe
        recipe_flow = recipe.model_values.get("flow_rate")
        self.flow_rate_note.value = (
            f"volume → time; blank = recipe ({recipe_flow / ML_PER_MIN:g} mL/min)"
            if recipe_flow is not None else "volume → time; blank = recipe (none set)"
        )
        self.overrides.load(recipe, comparison.overrides)

        self.component_fields.clear()
        for name in recipe.components:
            box = BoolField(label=name, value=name in (comparison.components or ()))
            box.observe(self._on_edit, names="value")
            self.component_fields[name] = box
        self.components_box.children = [
            note("Components (none = total):"),
            *self.component_fields.values(),
        ]

        options = [
            (f"{label} ({unit}.{port})", f"{unit}.{port}")
            for label, (unit, port) in check_recipe(recipe, comparison.overrides).signal_options
        ]
        if comparison.solution_path not in [v for _, v in options]:
            options.append((f"{comparison.solution_path} (not in process)",
                            comparison.solution_path))
        self.solution_path.set_options(options, keep_value=False)
        self.solution_path.value = comparison.solution_path

    def sync_visibility(self) -> None:
        """Show the injection and target-area fields only where they apply."""
        self.injection_x.layout.display = "" if self.marker.value is None else "none"
        self.target_area.layout.display = "" if self.normalization.value == "area" else "none"

    def invalid_fields(self) -> List[str]:
        """Return the labels of the fields holding invalid text."""
        fields = [
            self.name, self.flow_rate, self.injection_x, self.baseline_start,
            self.baseline_end, self.target_area, self.window_start, self.window_end,
            *self.overrides.elements(),
        ]
        return [f.label.rstrip(":") for f in fields if not f.is_valid]

    def draft(self, editing: Comparison) -> Comparison:
        """Return `editing` changed as the fields describe."""
        assert self.recipe is not None
        start, end = optional_float(self.baseline_start.value), optional_float(
            self.baseline_end.value
        )
        normalization: dict = {"kind": self.normalization.value}
        if self.normalization.value == "area":
            normalization["target_area"] = optional_float(self.target_area.value)
        components = [n for n, box in self.component_fields.items() if box.value]
        recipe = self.recipe
        probe, old = self.probe.value, editing.probe
        if probe and old and probe != old and old in recipe.components:
            recipe = dataclasses.replace(
                recipe, components=[probe if n == old else n for n in recipe.components]
            )
            components = [probe if n == old else n for n in components]
        return dataclasses.replace(
            editing,
            name=self.name.value.strip(),
            probe=probe,
            experiment_type=self.experiment_type.value,
            data_file=self.run.value or "",
            run=self.runs.get(self.run.value),
            channel=self.channel.value or "",
            flow_rate=read_flow_rate(self.flow_rate.value),
            recipe=recipe,
            overrides=self.overrides.read(),
            injection_marker=self.marker.value,
            measured_injection=(
                optional_float(self.injection_x.value) if self.marker.value is None else None
            ),
            baseline_window=None if start is None and end is None else (start, end),
            normalization=normalization,
            solution_path=self.solution_path.value or "",
            components=components or None,
            metric=self.metric.value,
            window=(
                optional_float(self.window_start.value),
                optional_float(self.window_end.value),
            ),
        )
