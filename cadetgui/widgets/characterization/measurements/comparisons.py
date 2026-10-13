from __future__ import annotations

import copy
import dataclasses
import html
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import CHAIN_BY_ID, map_species
from ....characterization.study import Study
from ....instrument.recipes import recipe_with_template
from ....io import configuration_store
from ....io.configuration_store import ConfigurationState
from ....io.experimental_data import ExperimentalRun
from ...ui.html import info_box_html, status_html
from ...ui.layout import panel
from ..help import term_html
from .add_flow import AddMeasurementFlow
from .labels import step_of
from .measurement_card import MeasurementCard
from .measurement_editor import ADVANCED_TITLE, METRICS, MeasurementEditor
from .measurement_list import MeasurementList
from .recipe_overrides import CURRENT_CONFIGURATION

if TYPE_CHECKING:
    from ...instrument.configuration import ConfigurationWidget

__all__ = ["ADVANCED_TITLE", "ComparisonsWidget", "METRICS"]

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


class ComparisonsWidget:
    """The Measurements pane: add, list, inspect and edit a study's comparisons.

    New measurements come from an in-pane stepper (`AddMeasurementFlow`). The list
    (`MeasurementList`) is grouped by the chain step each measurement feeds; the selected
    one is shown by a `MeasurementCard` (recipe, flow-path diagram, problems and the
    measured trace as the fit sees it) with a `MeasurementEditor` under Advanced. Edits
    are written through `study.replace_comparison`, so steps holding it see the new
    object. `configuration` supplies the base recipe of new measurements and can load or
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

        self._flow = AddMeasurementFlow(
            study, runs=self._known_runs, base_recipe=self._base_recipe,
            on_added=self._on_added, on_change=self._on_flow_change,
        )
        self._list = MeasurementList(
            study, self._flow,
            on_select=self._on_list_select, on_add=lambda step: self.start_add(step_id=step),
        )
        self._tables = self._list.tables
        self._list_box = self._list.box
        self._group_button = self._list.group_button

        self._editor = MeasurementEditor(study, check_name=self._check_name,
                                         on_edit=self._on_edit)
        self._measurement_card = MeasurementCard(self._editor.root)
        self._alias_parts()

        self._btn_duplicate = W.Button(description="Duplicate", icon="copy")
        self._btn_remove = W.Button(description="Remove", icon="trash")
        self.status = W.HTML("")
        self.status.add_class("cadetgui-status")
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
        self._btn_probe_role_fix.on_click(lambda _b: self.make_probe_fit())
        self._run.observe(self._on_run_change, names="selected_index")
        self._template.observe(self._on_template_change, names="selected_index")
        toolbar = W.HBox([self._btn_duplicate, self._btn_remove])
        toolbar.add_class("cadetgui-toolbar")

        self.root = panel(
            term_html("measurement", "Measurements"),
            W.HTML(info_box_html("What is a measurement?", _INTRO)),
            toolbar,
            self._remove_confirm,
            self.status,
            self._list_box,
            self._card,
        )

        study.add_listener(self._on_study_change)
        self._refresh_table()
        self._refresh_recipe_sources()
        self._load_editor()

    def _alias_parts(self) -> None:
        editor, card = self._editor, self._measurement_card
        self._card = card.root
        self._card_title = card.title
        self._recipe_summary = card.recipe.summary
        self._diagram = card.recipe.diagram
        self._problems_html = card.recipe.problems
        self._measured_chart = card.measured_chart
        self._measured_note = card.measured_note
        self._advanced = editor.root
        self._advanced_sections = editor.sections
        self._name = editor.name
        self._probe = editor.probe
        self._probe_role_fix = editor.role_fix.text
        self._btn_probe_role_fix = editor.role_fix.button
        self._experiment_type = editor.experiment_type
        self._run = editor.run
        self._channel = editor.channel
        self._data_file = editor.data_file
        self._flow_rate = editor.flow_rate
        self._flow_rate_note = editor.flow_rate_note
        self._marker = editor.marker
        self._injection_x = editor.injection_x
        self._baseline_start = editor.baseline_start
        self._baseline_end = editor.baseline_end
        self._normalization = editor.normalization
        self._target_area = editor.target_area
        self._solution_path = editor.solution_path
        self._components_box = editor.components_box
        self._component_fields = editor.component_fields
        self._metric = editor.metric
        self._window_start = editor.window_start
        self._window_end = editor.window_end
        self._template = editor.overrides.template
        self._template_note = editor.overrides.template_note
        self._recipe_source = editor.overrides.source
        self._btn_use_recipe = editor.overrides.use_recipe
        self._overrides_box = editor.overrides.box
        self._override_fields = editor.overrides.fields

    @property
    def selected(self) -> Optional[Comparison]:
        """The comparison shown in the card and editor."""
        return next((c for c in self.study.comparisons if c.name == self._selected_name), None)

    def select(self, name: str) -> None:
        """Show the comparison called `name`."""
        self._selected_name = name
        self._list.select(name)
        self._load_editor()

    def start_add(
        self, *, step_id: Optional[str] = None, experiment_type: Optional[str] = None
    ) -> None:
        """Open the add-measurement stepper, preselecting a step's or a given experiment type."""
        self._flow.start(step_id=step_id, experiment_type=experiment_type)

    # List

    def _refresh_table(self) -> None:
        names = [c.name for c in self.study.comparisons]
        if self._selected_name not in names and not self._committing:
            self._selected_name = names[0] if names else None
        self._list.refresh(self._selected_name)
        self._btn_duplicate.disabled = self._btn_remove.disabled = self.selected is None

    def _on_list_select(self, name: str) -> None:
        self._selected_name = name
        self._list.select(name)
        self._load_editor()
        self._btn_duplicate.disabled = self._btn_remove.disabled = self.selected is None

    def _on_study_change(self) -> None:
        self._refresh_table()
        editing = self._editing
        if self._committing:
            return
        if self.selected is not editing or (editing is not None and editing.recipe
                                            is not self._editor.recipe):
            self._load_editor()
        elif editing is not None:
            self._loading = True
            try:
                self._editor.fill_probe(editing.experiment_type, editing.probe)
            finally:
                self._loading = False
            self._show_card(editing)

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
        if hasattr(self, "_list"):
            self._refresh_table()

    def _on_added(self, comparison: Comparison, notes: List[str]) -> None:
        self._refresh_runs()
        self.select(comparison.name)
        guide = CHAIN_BY_ID.get(step_of(comparison) or "")
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
            name=self.study.unique_comparison_name(f"{source.name} copy"),
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
        editing = self._editing
        if editing is not None and editing.data_file not in runs:
            runs[editing.data_file] = editing.run
        was_loading = self._loading
        self._loading = True
        try:
            self._editor.set_runs(runs)
        finally:
            self._loading = was_loading

    def _refresh_recipe_sources(self) -> None:
        self._editor.overrides.fill_sources(
            with_configuration=self.configuration is not None,
            store_dir=self.configuration.persistence.store_dir if self.configuration else None,
        )

    def _load_editor(self) -> None:
        comparison = self.selected
        self._editing = comparison
        self._card.layout.display = "none" if comparison is None else ""
        if comparison is None:
            return
        self._loading = True
        try:
            self._refresh_runs()
            self._editor.load(comparison)
        finally:
            self._loading = False
        self._editor.sync_visibility()
        self._show_card(comparison)

    def make_probe_fit(self) -> None:
        """Give this measurement's component the role its experiment type needs."""
        target = self._editor.role_fix.target
        if target is None:
            return
        name, role = target
        self.study.set_component_role(name, role)
        self.status.value = status_html("ok", f"{name} is now a {role}.")

    def _show_card(self, comparison: Comparison) -> None:
        self._measurement_card.show(comparison, self.study.measurement_problems(comparison))

    def _on_run_change(self, _change: dict) -> None:
        if self._loading or self._editing is None:
            return
        run = self._editor.runs.get(self._run.value)
        draft = dataclasses.replace(self._editing, data_file=self._run.value or "", run=run)
        if run is not None and draft.channel not in run.channels:
            draft.channel = next(iter(run.channels), "")
        if run is not None and draft.injection_marker is not None and not any(
            text.startswith(draft.injection_marker) for _, text in run.markers
        ):
            draft.injection_marker = None
        self._loading = True
        try:
            self._editor.load_run_dependents(run, draft)
        finally:
            self._loading = False
        self._on_edit()

    def _on_template_change(self, _change: dict) -> None:
        recipe = self._editor.recipe
        if self._loading or self._editing is None or recipe is None:
            return
        template = self._template.value
        if template is None or template == recipe.template_key:
            return
        self._set_recipe(recipe_with_template(recipe, template))

    def _on_use_recipe(self, _btn: Any) -> None:
        if self._editing is None:
            return
        source = self._recipe_source.value
        try:
            if source is None:
                recipe = self._editing.recipe
            elif source == CURRENT_CONFIGURATION:
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
            self._editor.load_recipe(recipe, draft)
        finally:
            self._loading = False
        self._on_edit()

    def _on_edit(self, _change: Optional[dict] = None) -> None:
        if self._loading or self._editing is None:
            return
        self._editor.sync_visibility()
        invalid = self._editor.invalid_fields()
        if invalid:
            self._problems_html.value = status_html(
                "error", f"Fix {', '.join(invalid)} under Advanced to save this measurement."
            )
            return
        draft = self._editor.draft(self._editing)
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
            self._editor.fill_probe(draft.experiment_type, draft.probe)
            if draft.recipe is not self._editor.recipe:
                self._editor.load_recipe(draft.recipe, draft)
        finally:
            self._loading = False
        self._list.select(self._selected_name)
        self._show_card(draft)

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Call `fn()` whenever the study changes."""
        self.study.add_listener(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
