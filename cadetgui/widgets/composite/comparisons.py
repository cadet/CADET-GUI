from __future__ import annotations

import copy
import dataclasses
import html
import math
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

import ipywidgets as W
import numpy as np

from ...cadetprocessadapter import (
    FieldSpec,
    parse_float_list,
)
from ...characterization.comparison import Comparison
from ...characterization.guide import (
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    map_species,
    role_fix,
)
from ...characterization.study import Study
from ...io import configuration_store
from ...io.configuration_store import ConfigurationState
from ...io.experimental_data import (
    ExperimentalRun,
    to_time,
)
from ...process_builder import check_recipe
from .._chrome import style_tag
from .._help import info_box_html, term_html
from .._status import status_html
from ..elements import (
    BoolField,
    ChoiceField,
    ChromatogramChart,
    SelectableTable,
    TextField,
)
from ._measurement_common import (
    ML_PER_MIN,
    _check_float,
    _check_float_list,
    _format,
    _format_value,
    _note,
    _observed_unit,
    _optional_float,
    _row,
    _step_of,
    _template_fields,
    _template_options,
    _title,
    channel_label,
    component_options,
    problems_html,
    recipe_summary_html,
    recipe_with_template,
)
from .system_diagram import recipe_diagram_svg

if TYPE_CHECKING:
    from .configuration import ConfigurationWidget

from .add_measurement import AddMeasurementFlow

__all__ = ["ComparisonsWidget", "METRICS"]

# CADET-Process difference metrics that `setup_comparators` builds from the name alone.
METRICS: Tuple[str, ...] = (
    "NRMSE", "RMSE", "SSE", "L1", "L2", "AbsoluteArea", "RelativeArea",
    "Shape", "ShapeFront", "PeakHeight", "PeakPosition",
)

_CONFIG = "__configuration__"
_MAX_POINTS = 2000

_INTRO = (
    "<p>A " + term_html("measurement") + " is one recorded run (a data file with one or "
    "more detector channels) paired with the " + term_html("recipe") + " that should "
    "reproduce it: which units are in the " + term_html("flow path") + ", where the detector "
    "sits (the " + term_html("observation point") + "), and how the trace is aligned "
    "(" + term_html("injection marker") + ") and scaled (" + term_html("normalization")
    + ").</p><p>Each measurement feeds one characterization step, set by its experiment "
    "type. Add a "
    "measurement for every run you want a step to fit; the step compares the simulated "
    "signal to the measured one with a metric such as " + term_html("NRMSE") + ".</p>"
)


ADVANCED_TITLE = (
    "Advanced: fine-tune how this measurement is compared — the defaults from its "
    "experiment type are usually right."
)
_MEASURED_HINT = (
    "The measured trace as the fit compares it: shifted onto the simulated injection, "
    "baseline-corrected and scaled. Check alignment and baseline here; the step pages "
    "compare it with simulations."
)


def _subsection(title: str, when: str, children: Sequence[W.Widget]) -> W.VBox:
    box = W.VBox([
        W.HTML(f"<div class='cadetgui-section-title'>{html.escape(title)}</div>"),
        _note(f"<small>{html.escape(when)}</small>"),
        *children,
    ])
    box.add_class("cadetgui-subsection")
    return box


class ComparisonsWidget:
    """The Measurements pane: add, list, inspect and edit a study's comparisons.

    New measurements come from an in-pane stepper (upload → channel → experiment type →
    details → confirm). The list is grouped by the chain step each measurement feeds;
    the selected one shows a plain recipe card, its flow-path diagram, problems and the
    measured trace as the fit sees it (no simulation). Every field of the comparison is
    editable under Advanced, grouped in titled sections (`_advanced_sections`), and
    written through `study.replace_comparison`, so steps holding it see the new object.
    A component whose role does not fit the experiment type is listed as such, with an
    explicit "Make <name> a <role>" action when no other measurement needs its role.
    `configuration` supplies the base recipe of new measurements and can load or
    supply a measurement's recipe.
    """

    def __init__(
        self,
        study: Study,
        *,
        configuration: Optional["ConfigurationWidget"] = None,
    ) -> None:
        self.study = study
        self.configuration = configuration
        self._loading = False
        self._committing = False
        self._selected_name: Optional[str] = None
        self._editing: Optional[Comparison] = None
        self._recipe: Optional[ConfigurationState] = None
        self._runs: Dict[str, Optional[ExperimentalRun]] = {}
        self._override_fields: Dict[str, Tuple[FieldSpec, Any]] = {}
        self._component_fields: Dict[str, BoolField] = {}
        self._tables: Dict[Optional[str], SelectableTable] = {}
        self._group_buttons: Dict[str, W.Button] = {}

        self._flow = AddMeasurementFlow(
            study, runs=self._known_runs, base_recipe=self._base_recipe,
            on_added=self._on_added, on_change=self._on_flow_change,
        )
        self._btn_duplicate = W.Button(description="Duplicate", icon="copy")
        self._btn_remove = W.Button(description="Remove", icon="trash")
        self.status = W.HTML("")
        self.status.add_class("cadetgui-status")
        self._list_box = W.VBox([])

        self._card_title = W.HTML()
        self._recipe_summary = W.HTML()
        self._diagram = W.HTML()
        self._problems_html = W.HTML()
        self._problems_html.add_class("cadetgui-status")
        self._name = TextField(label="Name:", validate=self._check_name)
        self._probe = ChoiceField(label="Component:")
        self._probe_role_fix = W.HTML()
        self._probe_role_fix_target: Optional[Tuple[str, str]] = None
        self._btn_probe_role_fix = W.Button(
            icon="exchange", button_style="warning",
            layout=W.Layout(width="auto", display="none"),
        )
        self._btn_probe_role_fix.on_click(lambda _b: self.make_probe_fit())
        self._experiment_type = ChoiceField(
            label="Experiment type:",
            options=[("Not set", None), *((t.label, t.id) for t in EXPERIMENT_TYPES.values())],
        )
        self._run = ChoiceField(label="Data run:")
        self._channel = ChoiceField(label="Channel:")
        self._data_file = W.HTML()
        self._flow_rate = TextField(label="Run flow rate:", units="mL/min", validate=_check_float)
        self._flow_rate_note = _note()

        self._template = ChoiceField(label="Process template:")
        self._template_note = _note(
            "Changing the process template changes this measurement's method: its timing "
            "and concentrations go back to the new template's defaults (the flow rate is "
            "kept). Experiment types set their template for you; change it only if the run "
            "followed another method."
        )
        self._recipe_source = ChoiceField(label="Recipe from:")
        self._btn_use_recipe = W.Button(description="Use recipe", icon="download")
        self._overrides_box = W.HBox(layout=W.Layout(flex_flow="row wrap"))

        self._marker = ChoiceField(label="Injection marker:")
        self._injection_x = TextField(label="Injection at:", validate=_check_float)
        self._baseline_start = TextField(label="Baseline from:", validate=_check_float)
        self._baseline_end = TextField(label="to:", validate=_check_float)
        self._normalization = ChoiceField(
            label="Normalization:", options=[("None", "none"), ("Area", "area")]
        )
        self._target_area = TextField(label="Target area:", validate=_check_float)

        self._solution_path = ChoiceField(label="Observation point:")
        self._components_box = W.HBox(layout=W.Layout(flex_flow="row wrap"))
        self._metric = ChoiceField(label="Metric:", options=[(m, m) for m in METRICS])
        self._window_start = TextField(label="Compare from:", units="s", validate=_check_float)
        self._window_end = TextField(label="to:", units="s", validate=_check_float)

        self._measured_chart = ChromatogramChart(
            view_width=480, view_height=240, y_label="Signal", x_label="Time / min"
        )
        self._measured_note = _note()

        self._remove_note = W.HTML()
        self._btn_remove_confirm = W.Button(
            description="Remove from those steps too", icon="trash", button_style="danger",
            layout=W.Layout(width="auto"),
        )
        self._btn_remove_cancel = W.Button(description="Keep it", icon="times")
        self._remove_confirm = W.HBox(
            [self._remove_note, self._btn_remove_confirm, self._btn_remove_cancel],
            layout=W.Layout(display="none", flex_flow="row wrap", align_items="center"),
        )
        self._btn_remove_confirm.on_click(lambda _b: self.remove_selected(from_steps=True))
        self._btn_remove_cancel.on_click(lambda _b: self._hide_remove_confirm())
        self._btn_duplicate.on_click(self._on_duplicate)
        self._btn_remove.on_click(self._on_remove)
        self._btn_use_recipe.on_click(self._on_use_recipe)
        self._run.observe(self._on_run_change, names="selected_index")
        self._template.observe(self._on_template_change, names="selected_index")
        for choice in (self._channel, self._marker, self._normalization,
                       self._solution_path, self._metric, self._experiment_type, self._probe):
            choice.observe(self._on_edit, names="selected_index")
        for text in (self._name, self._flow_rate, self._injection_x,
                     self._baseline_start, self._baseline_end, self._target_area,
                     self._window_start, self._window_end):
            text.observe(self._on_edit, names="value")
        toolbar = W.HBox([self._btn_duplicate, self._btn_remove])
        toolbar.add_class("cadetgui-toolbar")
        self._advanced_sections: Dict[str, W.VBox] = {
            title: _subsection(title, when, children)
            for title, when, children in (
                (
                    "Data and alignment",
                    "Change when the wrong run or detector channel is used, or the measured "
                    "trace is shifted in time against the simulation.",
                    [
                        _row(self._run, self._channel, self._data_file),
                        _row(self._flow_rate, self._flow_rate_note),
                        _title(term_html("injection marker", "Injection marker")),
                        _row(self._marker, self._injection_x),
                    ],
                ),
                (
                    "Baseline and scaling",
                    "Change when the measured baseline drifts or the trace needs another "
                    "scale, e.g. to match the injected amount.",
                    [
                        _title(term_html("baseline window", "Baseline window")),
                        _row(self._baseline_start, self._baseline_end),
                        _title(term_html("normalization", "Normalization")),
                        _row(self._normalization, self._target_area),
                    ],
                ),
                (
                    "Simulated signal",
                    "Change when the detector sits elsewhere in the flow path or another "
                    "component should be compared.",
                    [
                        _title(term_html("observation point", "Observation point")
                               + " (solution path) and component"),
                        _row(self._solution_path, self._probe),
                        _row(self._probe_role_fix, self._btn_probe_role_fix),
                        self._components_box,
                    ],
                ),
                (
                    "Comparison",
                    "Change to use another error measure, or to compare only part of the "
                    "run (e.g. leave out a noisy tail).",
                    [_row(self._metric), _row(self._window_start, self._window_end)],
                ),
                (
                    "Process",
                    "Change only if the run followed another method than its experiment "
                    "type assumes.",
                    [
                        _row(self._template),
                        self._template_note,
                        _title(term_html("recipe", "Recipe") + " source and method overrides"),
                        _row(self._recipe_source, self._btn_use_recipe),
                        self._overrides_box,
                    ],
                ),
                (
                    "Name and type",
                    "Change to rename the measurement or give it another experiment type.",
                    [
                        _row(self._name, self._experiment_type),
                        _note("Changing the experiment type moves the measurement to another "
                              "step's group; it does not rebuild the recipe (add the run "
                              "again for that)."),
                    ],
                ),
            )
        }
        self._editor = W.VBox(list(self._advanced_sections.values()))
        self._advanced = W.Accordion(children=[self._editor], selected_index=None)
        self._advanced.set_title(0, ADVANCED_TITLE)

        self._card = W.VBox(
            [
                self._card_title,
                self._recipe_summary,
                self._diagram,
                _title("Problems"),
                self._problems_html,
                _title("Measured trace"),
                _note(_MEASURED_HINT),
                self._measured_chart,
                self._measured_note,
                self._advanced,
            ]
        )
        self._card.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>"
                       + term_html("measurement", "Measurements") + "</div>"),
                W.HTML(info_box_html("What is a measurement?", _INTRO)),
                toolbar,
                self._remove_confirm,
                self.status,
                self._list_box,
                self._card,
            ]
        )
        self.root.add_class("cadetgui-panel")

        study.add_listener(self._on_study_change)
        self._refresh_table()
        self._refresh_recipe_sources()
        self._load_editor()

    @property
    def selected(self) -> Optional[Comparison]:
        """The comparison shown in the card and editor."""
        return next((c for c in self.study.comparisons if c.name == self._selected_name), None)

    def select(self, name: str) -> None:
        """Show the comparison called `name`."""
        self._selected_name = name
        self._sync_table_selection()
        self._load_editor()

    def start_add(
        self, *, step_id: Optional[str] = None, experiment_type: Optional[str] = None
    ) -> None:
        """Open the add-measurement stepper, preselecting a step's or a given experiment type."""
        self._flow.start(step_id=step_id, experiment_type=experiment_type)

    # List

    def _group_order(self, groups: Dict[Optional[str], List[Comparison]]) -> List[Optional[str]]:
        return [g.id for g in DEFAULT_CHAIN] + ([None] if None in groups else [])

    def _table_for(self, key: Optional[str]) -> SelectableTable:
        if key not in self._tables:
            table = SelectableTable(
                columns=["Name", "Experiment type", "Detector", "Used in", "Status"],
                empty_text="No measurements yet.",
            )
            table.observe(lambda _c, key=key: self._on_table_select(key), names="selected_index")
            self._tables[key] = table
        return self._tables[key]

    def _group_button(self, step_id: str) -> W.Button:
        if step_id not in self._group_buttons:
            button = W.Button(description="Add measurement for this step", icon="plus",
                              layout=W.Layout(width="auto"))
            button.on_click(lambda _b: self.start_add(step_id=step_id))
            self._group_buttons[step_id] = button
        return self._group_buttons[step_id]

    def _refresh_table(self) -> None:
        names = [c.name for c in self.study.comparisons]
        if self._selected_name not in names and not self._committing:
            self._selected_name = names[0] if names else None
        groups: Dict[Optional[str], List[Comparison]] = {}
        for c in self.study.comparisons:
            groups.setdefault(_step_of(c), []).append(c)
        children: List[W.Widget] = []
        order = self._group_order(groups)
        target = self._flow.target_step if self._flow.is_open else None
        placed = target in order

        def flow_here(key: Optional[str]) -> bool:
            return self._flow.is_open and placed and key == target

        if self._flow.is_open and not placed:
            children.append(self._flow.root)
        was_loading = self._loading
        self._loading = True
        try:
            for key in order:
                members = groups.get(key, [])
                guide = CHAIN_BY_ID.get(key) if key is not None else None
                if guide is not None:
                    labels = ", ".join(EXPERIMENT_TYPES[t].label for t in guide.experiment_types)
                    heading = _title(f"{html.escape(guide.title)} "
                                     f"<span class='cadetgui-note'>· {len(members)} "
                                     f"measurement(s) · expects: {html.escape(labels)}</span>")
                else:
                    heading = _title(
                        "Not assigned to a step <span class='cadetgui-note'>· set an "
                        "experiment type under Advanced to assign one</span>"
                    )
                children.append(heading)
                if flow_here(key):
                    children.append(self._flow.root)
                if members:
                    table = self._table_for(key)
                    table.set_options(
                        [(c.name, c.name) for c in members],
                        rows=[self._row_cells(c) for c in members],
                        select_none=True,
                    )
                    children.append(table)
                if guide is not None and not flow_here(key):
                    children.append(self._group_button(key))
            self._tables = {k: t for k, t in self._tables.items() if groups.get(k)}
        finally:
            self._loading = was_loading
        self._list_box.children = children
        self._sync_table_selection()
        self._btn_duplicate.disabled = self._btn_remove.disabled = self.selected is None

    def _row_cells(self, c: Comparison) -> List[Any]:
        n = len(self.study.measurement_problems(c))
        chip = ("ok", "ok") if n == 0 else (f"{n} problem{'s' * (n > 1)}", "error")
        experiment_type = EXPERIMENT_TYPES.get(c.experiment_type or "")
        return [
            c.name,
            experiment_type.label if experiment_type else "not set",
            channel_label(c.channel),
            ", ".join(self.study.steps_using(c.name)) or "–",
            chip,
        ]

    def _sync_table_selection(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            for table in self._tables.values():
                table.value = self._selected_name
        finally:
            self._loading = was_loading

    def _on_table_select(self, key: Optional[str]) -> None:
        table = self._tables.get(key)
        if self._loading or table is None or table.value is None:
            return
        self._selected_name = table.value
        self._sync_table_selection()
        self._load_editor()
        self._btn_duplicate.disabled = self._btn_remove.disabled = self.selected is None

    def _on_study_change(self) -> None:
        self._refresh_table()
        editing = self._editing
        if self._committing:
            return
        if self.selected is not editing or (editing is not None and editing.recipe
                                            is not self._recipe):
            self._load_editor()
        elif editing is not None:
            self._loading = True
            try:
                self._fill_probe(editing.experiment_type, editing.probe)
            finally:
                self._loading = False
            self._show_card(editing)

    def _unique_name(self, base: str) -> str:
        names = {c.name for c in self.study.comparisons}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def _base_recipe(self) -> Tuple[Optional[ConfigurationState], str]:
        """Return the recipe new measurements start from and where it comes from."""
        if self.configuration is not None:
            source = (
                "the current process in Process Configuration"
                if getattr(self.configuration, "show_process_template", True)
                else "your System setup (hardware, flow rate, column and binding settings)"
            )
            try:
                return self.configuration.snapshot(), source
            except RuntimeError:
                pass
        if self.study.comparisons:
            first = self.study.comparisons[0]
            return copy.deepcopy(first.recipe), (
                f"the recipe of measurement {first.name!r} (no process built in "
                "Process Configuration)"
            )
        return None, "none; build a process in Process Configuration first"

    def _known_runs(self) -> Dict[str, Optional[ExperimentalRun]]:
        runs: Dict[str, Optional[ExperimentalRun]] = {}
        for c in self.study.comparisons:
            if runs.get(c.data_file) is None:
                runs[c.data_file] = c.run
        known = {id(r) for r in runs.values() if r is not None}
        for key, run in self._flow.uploaded.items():
            if id(run) not in known:
                known.add(id(run))
                runs.setdefault(key, run)
        return runs

    def _on_flow_change(self) -> None:
        if hasattr(self, "_list_box"):
            self._refresh_table()

    def _on_added(self, comparison: Comparison, notes: List[str]) -> None:
        self._refresh_runs()
        self.select(comparison.name)
        guide = CHAIN_BY_ID.get(_step_of(comparison) or "")
        text = f"Added {comparison.name}." + (
            f" It feeds the step {guide.title!r}; attach it there." if guide else ""
        )
        self.status.value = "<br>".join(
            [status_html("ok", text), *(status_html("info", n) for n in notes)]
        )

    def _on_duplicate(self, _btn: Any) -> None:
        source = self.selected
        if source is None:
            return
        comparison = dataclasses.replace(
            source,
            name=self._unique_name(f"{source.name} copy"),
            recipe=copy.deepcopy(source.recipe),
            overrides=copy.deepcopy(source.overrides),
            normalization=dict(source.normalization),
        )
        self.study.upsert_comparison(comparison)
        self.select(comparison.name)
        self.status.value = status_html("ok", f"Duplicated {source.name}.")

    def _on_remove(self, _btn: Any) -> None:
        comparison = self.selected
        if comparison is None:
            return
        users = self.study.steps_using(comparison.name)
        if not users:
            self.remove_selected()
            return
        self._remove_note.value = (
            f"<b>{html.escape(comparison.name)}</b> is fitted by step(s) "
            f"{html.escape(', '.join(users))}. Removing it takes it out of those steps and "
            "discards their fit results that are not accepted yet; accepted values stay in "
            "the parameter store."
        )
        self._remove_confirm.layout.display = ""

    def _hide_remove_confirm(self) -> None:
        self._remove_confirm.layout.display = "none"

    def remove_selected(self, *, from_steps: bool = False) -> None:
        """Remove the selected measurement; `from_steps` also takes it out of the steps."""
        self._hide_remove_confirm()
        comparison = self.selected
        if comparison is None:
            return
        index = self.study.comparisons.index(comparison)
        try:
            self.study.remove_comparison(comparison.name, from_steps=from_steps)
        except ValueError as exc:
            self.status.value = status_html("error", str(exc))
            return
        if self.study.comparisons:
            self.select(self.study.comparisons[min(index, len(self.study.comparisons) - 1)].name)
        self.status.value = status_html("ok", f"Removed {comparison.name}.")

    def _configuration_recipe(self) -> ConfigurationState:
        """Return the configuration's recipe for the edited measurement.

        With the configuration's process template hidden, only the system is taken from
        it (column, binding model and their values, hardware values); the measurement
        keeps its components, process template, method values and how its run uses the
        hardware (bypassed units, sample loop).
        """
        recipe = self.configuration.snapshot()
        editing = self._editing
        if getattr(self.configuration, "show_process_template", True) or editing is None:
            return recipe
        own = editing.recipe
        instrument = own.instrument
        if recipe.instrument is not None and own.instrument is not None:
            instrument = dataclasses.replace(
                recipe.instrument,
                bypass_units=list(own.instrument.bypass_units),
                include_sample_loop=own.instrument.include_sample_loop,
                unit_values={**own.instrument.unit_values, **recipe.instrument.unit_values},
            )
        same_binding = recipe.binding_key == own.binding_key
        return dataclasses.replace(
            own,
            column_key=recipe.column_key,
            column_values=map_species(
                recipe.column_values, recipe.components, own.components
            ),
            binding_values=(
                map_species(recipe.binding_values, recipe.components, own.components)
                if same_binding else copy.deepcopy(own.binding_values)
            ),
            multiplex_state=dict(recipe.multiplex_state),
            instrument=instrument,
        )

    # Editor

    def _check_name(self, name: str) -> Optional[str]:
        if not name.strip():
            return "A name is required."
        current = self._editing.name if self._editing is not None else None
        if name != current and any(c.name == name for c in self.study.comparisons):
            return f"{name!r} is already used."
        return None

    def _refresh_runs(self) -> None:
        runs = self._known_runs()
        self._runs = runs
        editing = self._editing
        if editing is not None and editing.data_file not in runs:
            runs[editing.data_file] = editing.run
        labels = [
            (f"{key} ({len(run.channels)} channels)" if run is not None else f"{key} (not loaded)",
             key)
            for key, run in runs.items()
        ]
        was_loading = self._loading
        self._loading = True
        try:
            self._run.set_options(labels)
        finally:
            self._loading = was_loading

    def _refresh_recipe_sources(self) -> None:
        options: List[Tuple[str, Any]] = [("Keep this measurement's recipe", None)]
        if self.configuration is not None:
            options.append(("Current configuration", _CONFIG))
        store_dir = self.configuration.persistence.store_dir if self.configuration else None
        options.extend(
            (f"Saved: {name} ({hash_[:8]})", hash_)
            for name, hash_ in configuration_store.list_store(store_dir=store_dir)
        )
        self._recipe_source.set_options(options, keep_value=False)

    def _signal_options(self, recipe: ConfigurationState, overrides: dict) -> List[Tuple[str, str]]:
        return [
            (f"{label} ({unit}.{port})", f"{unit}.{port}")
            for label, (unit, port) in check_recipe(recipe, overrides).signal_options
        ]

    def _load_editor(self) -> None:
        comparison = self.selected
        self._editing = comparison
        self._card.layout.display = "none" if comparison is None else ""
        if comparison is None:
            return
        self._loading = True
        try:
            self._name.value = comparison.name
            self._name._run_validate()
            self._experiment_type.value = comparison.experiment_type
            self._fill_probe(comparison.experiment_type, comparison.probe)
            self._refresh_runs()
            self._run.value = comparison.data_file
            self._flow_rate.value = (
                _format(comparison.flow_rate / ML_PER_MIN)
                if comparison.flow_rate is not None else ""
            )
            baseline = comparison.baseline_window or (None, None)
            self._baseline_start.value = _format(baseline[0])
            self._baseline_end.value = _format(baseline[1])
            self._injection_x.value = _format(comparison.measured_injection)
            self._normalization.value = comparison.normalization.get("kind", "none")
            self._target_area.value = _format(comparison.normalization.get("target_area"))
            self._metric.set_options(
                [(m, m) for m in dict.fromkeys((*METRICS, comparison.metric))], keep_value=False
            )
            self._metric.value = comparison.metric
            self._window_start.value = _format(comparison.window[0])
            self._window_end.value = _format(comparison.window[1])
            self._load_run_dependents(comparison.run, comparison)
            self._load_recipe(comparison.recipe, comparison)
        finally:
            self._loading = False
        self._sync_visibility()
        self._show_card(comparison)

    def _fill_probe(self, type_id: Optional[str], probe: Optional[str]) -> None:
        """Offer the declared components whose role fits `type_id`; keep `probe` listed."""
        experiment_type = EXPERIMENT_TYPES.get(type_id or "")
        roles = experiment_type.probe_roles if experiment_type is not None else None
        options: List[Tuple[str, Optional[str]]] = [("None", None)]
        options += component_options(self.study, roles)
        if probe is not None and probe not in [v for _, v in options]:
            component = self.study.component(probe)
            note = f"{component.role}, does not fit" if component else "not declared"
            options.append((f"{probe} ({note})", probe))
        self._probe.set_options(options, keep_value=False)
        self._probe.value = probe
        text, target = role_fix(self.study, probe, experiment_type) if (
            probe and experiment_type is not None
        ) else ("", None)
        self._probe_role_fix_target = (probe, target) if target is not None else None
        self._probe_role_fix.value = status_html("warn", text) if text else ""
        if target is not None:
            self._btn_probe_role_fix.description = f"Make {probe} a {target}"
        self._btn_probe_role_fix.layout.display = "" if target is not None else "none"

    def make_probe_fit(self) -> None:
        """Give this measurement's component the role its experiment type needs."""
        if self._probe_role_fix_target is None:
            return
        name, role = self._probe_role_fix_target
        self.study.set_component_role(name, role)
        self.status.value = status_html("ok", f"{name} is now a {role}.")

    def _load_run_dependents(self, run: Optional[ExperimentalRun], comparison: Comparison) -> None:
        channels = list(run.channels) if run is not None else []
        if comparison.channel and comparison.channel not in channels:
            channels.append(comparison.channel)
        self._channel.set_options([(c, c) for c in channels], keep_value=False)
        self._channel.value = comparison.channel

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
        self._marker.set_options(options, keep_value=False)
        self._marker.value = marker

        x_unit = run.x_unit if run is not None else ""
        for field in (self._injection_x, self._baseline_start, self._baseline_end):
            field.units = x_unit
        file_note = f"file: {html.escape(comparison.data_file)}" if comparison.data_file else ""
        self._data_file.value = f"<span class='cadetgui-note'>{file_note}</span>"

    def _load_recipe(self, recipe: ConfigurationState, comparison: Comparison) -> None:
        self._recipe = recipe
        self._template.set_options(_template_options(recipe), keep_value=False)
        self._template.value = recipe.template_key
        recipe_flow = recipe.model_values.get("flow_rate")
        self._flow_rate_note.value = (
            f"volume → time; blank = recipe ({recipe_flow / ML_PER_MIN:g} mL/min)"
            if recipe_flow is not None else "volume → time; blank = recipe (none set)"
        )

        self._override_fields = {}
        children = [_note("Overrides (blank = recipe value)")]
        for spec in _template_fields(recipe):
            current = comparison.overrides.get(spec.name)
            recipe_value = recipe.model_values.get(spec.name, spec.default)
            label = f"{spec.label or spec.name} [recipe {_format_value(recipe_value)}]:"
            if spec.kind == "choice":
                element: Any = ChoiceField(
                    label=label,
                    options=[(f"recipe ({recipe_value})", None), *(spec.options or ())],
                    value=current,
                )
                element.observe(self._on_edit, names="selected_index")
            else:
                shown = (
                    ", ".join(f"{v:g}" for v in current) if spec.kind == "float_list" and current
                    else _format(current)
                )
                element = TextField(
                    label=label,
                    value=shown,
                    units=spec.units,
                    validate=_check_float_list if spec.kind == "float_list" else _check_float,
                )
                element.observe(self._on_edit, names="value")
            self._override_fields[spec.name] = (spec, element)
            children.append(element)
        self._overrides_box.children = children

        self._component_fields = {}
        for name in recipe.components:
            box = BoolField(label=name, value=name in (comparison.components or ()))
            box.observe(self._on_edit, names="value")
            self._component_fields[name] = box
        self._components_box.children = [
            _note("Components (none = total):"),
            *self._component_fields.values(),
        ]

        options = list(self._signal_options(recipe, comparison.overrides))
        if comparison.solution_path not in [v for _, v in options]:
            options.append((f"{comparison.solution_path} (not in process)",
                            comparison.solution_path))
        self._solution_path.set_options(options, keep_value=False)
        self._solution_path.value = comparison.solution_path

    def _show_card(self, comparison: Comparison) -> None:
        self._card_title.value = (
            f"<div class='cadetgui-panel-title'>{html.escape(comparison.name)}</div>"
        )
        self._recipe_summary.value = recipe_summary_html(comparison)
        self._diagram.value = recipe_diagram_svg(
            comparison.recipe, observe=_observed_unit(comparison.solution_path), compact=True
        )
        problems = self.study.measurement_problems(comparison)
        unprepared = self._show_measured(comparison)
        if unprepared and not problems:
            problems = [unprepared]
        self._problems_html.value = problems_html(problems)

    def _show_measured(self, comparison: Comparison) -> Optional[str]:
        """Plot the measured trace as the fit compares it, else the raw trace; return why."""
        run = comparison.run
        if run is None or comparison.channel not in run.channels:
            self._measured_chart.series = []
            self._measured_note.value = "No measured data loaded."
            return None
        try:
            check = check_recipe(comparison.recipe, comparison.overrides)
            if check.error is not None:
                raise ValueError(check.error)
            reference = comparison.build_reference(check.process)
            time = np.asarray(reference.time)
            values = np.asarray(reference.solution)[:, 0]
            problem = None
        except Exception as exc:  # noqa: BLE001 -- shown with the raw trace instead
            time, values = to_time(run, comparison.channel, comparison.resolved_flow_rate)
            problem = str(exc)
        stride = max(1, math.ceil(time.size / _MAX_POINTS))
        self._measured_chart.series = [{
            "name": comparison.name,
            "times": (time[::stride] / 60.0).tolist(),
            "values": values[::stride].tolist(),
            "reference": True,
        }]
        self._measured_note.value = (
            status_html("warn", "Showing the raw trace; it cannot be prepared for the fit.")
            if problem else ""
        )
        return problem

    def _sync_visibility(self) -> None:
        self._injection_x.layout.display = "" if self._marker.value is None else "none"
        self._target_area.layout.display = "" if self._normalization.value == "area" else "none"

    def _on_run_change(self, _change: dict) -> None:
        if self._loading or self._editing is None:
            return
        run = self._runs.get(self._run.value)
        draft = dataclasses.replace(self._editing, data_file=self._run.value or "", run=run)
        if run is not None and draft.channel not in run.channels:
            draft.channel = next(iter(run.channels), "")
        if run is not None and draft.injection_marker is not None and not any(
            text.startswith(draft.injection_marker) for _, text in run.markers
        ):
            draft.injection_marker = None
        self._loading = True
        try:
            self._load_run_dependents(run, draft)
        finally:
            self._loading = False
        self._on_edit()

    def _on_template_change(self, _change: dict) -> None:
        if self._loading or self._editing is None or self._recipe is None:
            return
        template = self._template.value
        if template is None or template == self._recipe.template_key:
            return
        self._set_recipe(recipe_with_template(self._recipe, template))

    def _on_use_recipe(self, _btn: Any) -> None:
        if self._editing is None:
            return
        source = self._recipe_source.value
        try:
            if source is None:
                recipe = self._editing.recipe
            elif source == _CONFIG:
                recipe = self._configuration_recipe()
            else:
                store_dir = self.configuration.persistence.store_dir if self.configuration else None
                _, recipe = configuration_store.load_from_store(source, store_dir=store_dir)
        except (RuntimeError, FileNotFoundError) as exc:
            self.status.value = status_html("error", str(exc))
            return
        self._set_recipe(recipe)

    def _set_recipe(self, recipe: ConfigurationState) -> None:
        draft = dataclasses.replace(
            self._editing,
            recipe=recipe,
            components=[c for c in self._editing.components or () if c in recipe.components]
            or None,
        )
        self._loading = True
        try:
            self._load_recipe(recipe, draft)
        finally:
            self._loading = False
        self._on_edit()

    def _read_overrides(self) -> dict:
        overrides = {}
        for name, (spec, element) in self._override_fields.items():
            if spec.kind == "choice":
                if element.value is not None:
                    overrides[name] = element.value
            elif element.value.strip():
                overrides[name] = (
                    parse_float_list(element.value) if spec.kind == "float_list"
                    else float(element.value)
                )
        return overrides

    def _draft(self) -> Comparison:
        """Return the comparison the editor fields describe."""
        assert self._editing is not None and self._recipe is not None
        flow_rate = _optional_float(self._flow_rate.value)
        start, end = _optional_float(self._baseline_start.value), _optional_float(
            self._baseline_end.value
        )
        normalization: dict = {"kind": self._normalization.value}
        if self._normalization.value == "area":
            normalization["target_area"] = _optional_float(self._target_area.value)
        components = [n for n, box in self._component_fields.items() if box.value]
        recipe = self._recipe
        probe, old = self._probe.value, self._editing.probe
        if probe and old and probe != old and old in recipe.components:
            recipe = dataclasses.replace(
                recipe, components=[probe if n == old else n for n in recipe.components]
            )
            components = [probe if n == old else n for n in components]
        return dataclasses.replace(
            self._editing,
            name=self._name.value.strip(),
            probe=probe,
            experiment_type=self._experiment_type.value,
            data_file=self._run.value or "",
            run=self._runs.get(self._run.value),
            channel=self._channel.value or "",
            flow_rate=flow_rate * ML_PER_MIN if flow_rate is not None else None,
            recipe=recipe,
            overrides=self._read_overrides(),
            injection_marker=self._marker.value,
            measured_injection=(
                _optional_float(self._injection_x.value) if self._marker.value is None else None
            ),
            baseline_window=None if start is None and end is None else (start, end),
            normalization=normalization,
            solution_path=self._solution_path.value or "",
            components=components or None,
            metric=self._metric.value,
            window=(
                _optional_float(self._window_start.value),
                _optional_float(self._window_end.value),
            ),
        )

    def _invalid_fields(self) -> List[str]:
        fields = [
            self._name, self._flow_rate, self._injection_x, self._baseline_start,
            self._baseline_end, self._target_area, self._window_start, self._window_end,
            *(element for _, element in self._override_fields.values()),
        ]
        return [f.label.rstrip(":") for f in fields if not f.is_valid]

    def _on_edit(self, _change: Optional[dict] = None) -> None:
        if self._loading or self._editing is None:
            return
        self._sync_visibility()
        invalid = self._invalid_fields()
        if invalid:
            self._problems_html.value = status_html(
                "error", f"Fix {', '.join(invalid)} under Advanced to save this measurement."
            )
            return
        draft = self._draft()
        old_name = self._editing.name
        self._committing = True
        try:
            self._editing = draft
            self._selected_name = draft.name
            self.study.replace_comparison(old_name, draft)
        finally:
            self._committing = False
        self._loading = True
        try:
            self._fill_probe(draft.experiment_type, draft.probe)
            if draft.recipe is not self._recipe:
                self._load_recipe(draft.recipe, draft)
        finally:
            self._loading = False
        self._sync_table_selection()
        self._show_card(draft)

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Call `fn()` whenever the study changes."""
        self.study.add_listener(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
