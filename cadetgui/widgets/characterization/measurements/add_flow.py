"""The add-measurement stepper of the Measurements pane."""

from __future__ import annotations

import copy
import dataclasses
import html
from typing import Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import (
    CHAIN_BY_ID,
    EXPERIMENT_TYPES,
    ExperimentType,
    find_injection_marker,
    measurement_from_run,
    with_implied_values,
)
from ....characterization.study import Study
from ....instrument.process_builder import check_recipe
from ....instrument.recipes import recipe_flow_rate, recipe_with_template
from ....io.configuration_store import ConfigurationState
from ....io.experimental_data import ExperimentalRun
from ...elements import ChoiceField, TextField
from ...ui.html import status_html
from ...ui.layout import note, row, section_title
from ..help import term_html
from .channel_page import ChannelPage
from .component_picker import ComponentPicker
from .labels import check_float, flow_rate_text, read_flow_rate, same_value
from .recipe_view import RecipeView
from .step_types import StepTypeChoice
from .type_page import OTHER, ExperimentTypePage
from .upload import RunUpload

_PAGES = ("Upload", "Channel", "Experiment type", "Details", "Confirm")
_NO_BASE = "No base recipe: build a process in Process Configuration first."


class AddMeasurementFlow(RunUpload):
    """In-pane stepper: data file → channel → experiment type → details → a new comparison.

    Started for a step (or one of its experiment types), the experiment-type page is
    skipped: the Details page shows the step's type, or a choice among its types
    preselected by the channel's detector when that is unambiguous.

    `runs()` lists already loaded runs by data file; `base_recipe()` returns the recipe
    to start from and a sentence saying where it comes from; `on_added(comparison,
    notes)` is called after the comparison is in `study`.
    """

    def __init__(
        self,
        study: Study,
        *,
        runs: Callable[[], Dict[str, Optional[ExperimentalRun]]],
        base_recipe: Callable[[], Tuple[Optional[ConfigurationState], str]],
        on_added: Callable[[Comparison, List[str]], None],
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self.study = study
        self._runs = runs
        self._base_recipe = base_recipe
        self._on_added = on_added
        self._on_change = on_change
        self._start_step: Optional[str] = None
        self._visible_pages: Tuple[int, ...] = tuple(range(len(_PAGES)))
        self._title = W.HTML()
        self.page = 0
        self._prefilled_for: Optional[Tuple[Any, ...]] = None
        self._loading = False

        upload_page = self._init_upload()

        self._channel_page = ChannelPage()
        self._channel = self._channel_page.channel
        self._channel_chart = self._channel_page.chart
        self._markers = self._channel_page.markers

        self._type_page = ExperimentTypePage(base_recipe)
        self._type_table = self._type_page.table
        self._type_help = self._type_page.help
        self._other_template = self._type_page.other_template
        self._other_template_box = self._type_page.other_template_box

        self._step_types = StepTypeChoice(self._on_step_type)
        self._step_type = self._step_types.radio
        self._step_type_info = self._step_types.info
        self._step_type_box = self._step_types.root

        self._components = ComponentPicker(study, lambda: self.experiment_type)
        self._component = self._components.choice
        self._new_component = self._components.new_name
        self._new_role = self._components.new_role
        self._component_note = self._components.note
        self._role_fix = self._components.role_fix.text
        self._btn_role_fix = self._components.role_fix.button
        self._btn_role_fix.on_click(lambda _b: self.make_component_fit())

        self._name = TextField(label="Name:", validate=self._check_name)
        self._flow_rate = TextField(label="Flow rate:", units="mL/min", validate=check_float)
        self._marker = ChoiceField(label="Injection marker:")
        self._details_note = note()

        self._base_note = W.HTML()
        self._recipe_view = RecipeView()
        self._summary = self._recipe_view.summary
        self._diagram = self._recipe_view.diagram
        self._confirm_problems = self._recipe_view.problems
        self._implied = W.Checkbox(
            value=False, indent=False,
            description="Also add the values this experiment type assumes to the parameter store",
            layout=W.Layout(width="auto"),
        )
        self._implied_note = note()

        self._progress = W.HTML()
        self._btn_back = W.Button(description="Back", icon="arrow-left")
        self._btn_next = W.Button(description="Next", icon="arrow-right", button_style="primary")
        self._btn_add = W.Button(description="Add measurement", icon="check",
                                 button_style="success")
        self._btn_cancel = W.Button(description="Cancel", icon="times")
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")

        self._channel.observe(lambda _c: self._channel_page.show(self.run),
                              names="selected_index")
        self._type_table.observe(lambda _c: self._target_changed(), names="selected_index")
        self._btn_back.on_click(lambda _b: self.back())
        self._btn_next.on_click(lambda _b: self.next())
        self._btn_add.on_click(lambda _b: self.confirm())
        self._btn_cancel.on_click(lambda _b: self.close())

        self._pages = [
            upload_page,
            self._channel_page.root,
            self._type_page.root,
            W.VBox([
                self._step_type_box,
                row(self._name, self._component),
                row(self._new_component, self._new_role),
                self._component_note,
                self._components.role_fix.root,
                row(self._flow_rate, self._marker),
                self._details_note,
            ]),
            W.VBox([
                self._base_note,
                section_title(term_html("recipe", "Recipe") + " of the new measurement"),
                self._summary,
                self._diagram,
                self._confirm_problems,
                self._implied,
                self._implied_note,
            ]),
        ]
        nav = W.HBox([self._btn_back, self._btn_next, self._btn_add, self._btn_cancel])
        nav.add_class("cadetgui-toolbar")
        self.root = W.VBox([
            self._title,
            self._progress,
            *self._pages,
            self.status,
            nav,
        ])
        self.root.add_class("cadetgui-section")
        self.root.layout.display = "none"

    # Navigation

    @property
    def is_open(self) -> bool:
        """Whether the stepper is shown."""
        return self.root.layout.display != "none"

    def start(
        self, *, step_id: Optional[str] = None, experiment_type: Optional[str] = None
    ) -> None:
        """Open the stepper at the upload page.

        With a `step_id` or an `experiment_type` of a chain step, the experiment-type page
        is left out and the type is picked among that step's types on the Details page.
        An explicit `experiment_type` is preselected; with only a `step_id`, the channel's
        detector decides when it matches exactly one of the step's types, otherwise the
        step's first type is used.
        """
        explicit = experiment_type
        if experiment_type is None and step_id in CHAIN_BY_ID:
            experiment_type = CHAIN_BY_ID[step_id].experiment_types[0]
        self._start_step = step_id if step_id in CHAIN_BY_ID else (
            EXPERIMENT_TYPES[experiment_type].step_id if experiment_type in EXPERIMENT_TYPES
            else None
        )
        guide = CHAIN_BY_ID.get(self._start_step or "")
        fixed = guide is not None and experiment_type in guide.experiment_types
        self._step_types.reset(
            self._start_step if fixed else None,
            explicit=explicit, default=experiment_type if fixed else None,
        )
        self._visible_pages = (0, 1, 3, 4) if fixed else tuple(range(len(_PAGES)))
        self.run, self.data_file, self._pending = None, "", None
        self._roles_box.children = ()
        self._run_note.value = ""
        self._prefilled_for = None
        self._implied.value = False
        self.status.value = ""
        self._type_page.reset()
        options: List[Tuple[str, Optional[str]]] = [("Choose…", None)]
        options += [(key, key) for key, run in self._runs().items() if run is not None]
        self._loading = True
        try:
            self._loaded.set_options(options, keep_value=False)
            self._type_page.fill(self._channel.value, experiment_type)
        finally:
            self._loading = False
        self.root.layout.display = ""
        self._go(0)
        self._target_changed()

    def close(self) -> None:
        """Hide the stepper without adding anything."""
        self.root.layout.display = "none"
        self._target_changed()

    @property
    def target_step(self) -> Optional[str]:
        """The chain step the measurement being added feeds, if known."""
        experiment_type = self.experiment_type
        if experiment_type is not None:
            return experiment_type.step_id
        if self._type_table.value == OTHER:
            return None
        return self._start_step

    def _target_changed(self) -> None:
        guide = CHAIN_BY_ID.get(self.target_step or "")
        target = (
            f" for the step <b>{html.escape(guide.title)}</b>" if guide is not None
            else " (not assigned to a step)" if self._type_table.value == OTHER
            else ""
        )
        self._title.value = (
            "<div class='cadetgui-panel-title'>Add a " + term_html("measurement")
            + target + "</div>"
        )
        if self._on_change is not None:
            self._on_change()

    @property
    def pages(self) -> List[str]:
        """The names of the pages this stepper walks through."""
        return [_PAGES[i] for i in self._visible_pages]

    def _step_by(self, delta: int) -> None:
        pages = self._visible_pages
        index = pages.index(self.page) if self.page in pages else 0
        self._go(pages[min(max(index + delta, 0), len(pages) - 1)])

    def back(self) -> None:
        """Go to the previous page."""
        self._step_by(-1)

    def next(self) -> None:
        """Go to the next page if the current one is complete."""
        error = self._page_error()
        if error:
            self.status.value = status_html("error", error)
            return
        self._step_by(1)

    def _go(self, page: int) -> None:
        self.page = page
        self.status.value = ""
        if page == 1:
            self._loading = True
            try:
                self._channel_page.fill(self.run)
            finally:
                self._loading = False
            self._channel_page.show(self.run)
        elif page == 2:
            self._type_page.fill(self._channel.value, self._type_table.value)
        elif page == 3:
            self._fill_step_types()
            self._prefill_details()
        elif page == 4:
            self._show_confirm()
        for i, box in enumerate(self._pages):
            box.layout.display = "" if i == page else "none"
        self._btn_back.disabled = page == 0
        self._btn_next.layout.display = "none" if page == len(_PAGES) - 1 else ""
        self._btn_add.layout.display = "" if page == len(_PAGES) - 1 else "none"
        self._progress.value = " › ".join(
            f"<b>{n} {_PAGES[i]}</b>" if i == page else f"{n} {_PAGES[i]}"
            for n, i in enumerate(self._visible_pages, start=1)
        )

    def _page_error(self) -> Optional[str]:
        if self.page == 0 and self.run is None:
            return "Upload a data file or pick a loaded run first."
        if self.page == 1 and self._channel.value is None:
            return "Pick a channel."
        if self.page == 2 and self._type_table.value is None:
            return "Pick what you ran (the experiment type)."
        if self.page == 3:
            fields = [self._name, self._flow_rate]
            if self._components.is_new:
                fields.append(self._new_component)
            invalid = [f.label.rstrip(":") for f in fields if not f.is_valid]
            if invalid:
                return f"Fix {', '.join(invalid)} first."
            if self.experiment_type is not None and self._component.value is None:
                return "Pick the component you injected."
            text, target = self._components.role_fix_text()
            if text and not self._components.is_new:
                return text + (
                    " Change its role with the button, or pick another component."
                    if target is not None else ""
                )
        return None

    @property
    def experiment_type(self) -> Optional[ExperimentType]:
        """The chosen experiment type (`None` for 'Other' or no choice)."""
        return self._type_page.experiment_type

    # Details

    def _fill_step_types(self) -> None:
        choice = self._step_types.preselect(self._channel.value)
        if choice is not None:
            self._type_table.value = choice
        self._step_types.show(self._type_table.value)

    def _on_step_type(self, type_id: str) -> None:
        self._type_table.value = type_id
        if self.page == 3:
            self._prefill_details()

    def _check_name(self, name: str) -> Optional[str]:
        if not name.strip():
            return "A name is required."
        if any(c.name == name.strip() for c in self.study.comparisons):
            return f"{name!r} is already used."
        return None

    def make_component_fit(self) -> None:
        """Give the picked component the role this experiment needs, then select it."""
        target = self._components.role_fix.target
        if target is None:
            return
        name, role = target
        self.study.set_component_role(name, role)
        self._components.fill(name)
        self.status.value = status_html("ok", f"{name} is now a {role}.")

    @property
    def component(self) -> Optional[str]:
        """The chosen component's name (the new one's when "New component…" is picked)."""
        return self._components.value

    def new_component(self, name: str, role: Optional[str] = None) -> None:
        """Pick "New component…" with `name` (and `role`, else the type's first role)."""
        self._components.set_new(name, role)

    def _prefill_details(self) -> None:
        experiment_type = self.experiment_type
        base, _ = self._base_recipe()
        key = (self._type_table.value, self.data_file, self._channel.value, id(base))
        if key != self._prefilled_for:
            self._prefilled_for = key
            label = self.run.label if self.run is not None else "Measurement"
            self._name.value = self.study.unique_comparison_name(label)
            probes = [
                c.probe for c in self.study.comparisons
                if c.probe and experiment_type is not None
                and c.experiment_type == experiment_type.id
            ]
            self._components.fill(probes[0] if probes else None)
            flow_rate = None
            if base is not None:
                recipe = (
                    experiment_type.apply(base, component="Probe")
                    if experiment_type is not None else base
                )
                flow_rate = recipe_flow_rate(recipe)
            self._flow_rate.value = flow_rate_text(flow_rate)
            self._fill_markers(experiment_type)
        self._new_component._run_validate()
        self._details_note.value = (
            "The flow rate is prefilled from the recipe; change it if this run used "
            "another one. The " + term_html("injection marker") + " was picked from the run "
            "log by the experiment type's keywords; change it if it is wrong."
        )

    def _fill_markers(self, experiment_type: Optional[ExperimentType]) -> None:
        run = self.run
        options: List[Tuple[str, Optional[str]]] = [("None / manual", None)]
        options += [
            (f"{text} (at {x:g} {run.x_unit} in the run log)", text) for x, text in run.markers
        ]
        keywords = experiment_type.marker_keywords if experiment_type is not None else (
            "inject", "sample", "elution"
        )
        self._marker.set_options(options, keep_value=False)
        self._marker.value = find_injection_marker(run, keywords)

    # Confirm

    def draft(self) -> Comparison:
        """Return the comparison the current choices describe; raises without a base recipe."""
        base, _ = self._base_recipe()
        if base is None or self.run is None:
            raise ValueError("A base recipe and a run are needed.")
        name = self._name.value.strip()
        channel = self._channel.value or ""
        marker = self._marker.value
        flow_rate = read_flow_rate(self._flow_rate.value)
        experiment_type = self.experiment_type
        if experiment_type is None:
            recipe = copy.deepcopy(base)
            template = self._other_template.value
            if template is not None and template != base.template_key:
                recipe = recipe_with_template(recipe, template)
            recipe_flow = recipe_flow_rate(recipe)
            options = list(check_recipe(recipe).signal_options)
            unit, port = options[0][1] if options else ("outlet", "inlet")
            return Comparison(
                name=name,
                data_file=self.data_file,
                channel=channel,
                recipe=recipe,
                solution_path=f"{unit}.{port}",
                flow_rate=None if same_value(flow_rate, recipe_flow) else flow_rate,
                injection_marker=marker,
                probe=self.component,
                run=self.run,
            )
        component = self.component or ""
        recipe_flow = experiment_type.apply(base, component=component).model_values.get(
            "flow_rate"
        )
        comparison = measurement_from_run(
            name, self.run, channel, experiment_type, base,
            component=component,
            flow_rate=None if same_value(flow_rate, recipe_flow) else flow_rate,
            injection_marker=marker,
        )
        return dataclasses.replace(comparison, data_file=self.data_file, injection_marker=marker)

    def _show_confirm(self) -> None:
        base, source = self._base_recipe()
        self._base_note.value = (
            "<p class='cadetgui-note'>Base " + term_html("recipe") + ": "
            + html.escape(source, quote=False) + ".</p>"
        )
        experiment_type = self.experiment_type
        implied = experiment_type.implied if experiment_type is not None else ()
        self._implied.layout.display = "" if implied else "none"
        self._implied_note.value = (
            "This experiment type assumes: " + "; ".join(
                html.escape(f"{item.path} = {item.value:g} ({item.note})") for item in implied
            ) + ". Nothing is written unless you tick the box."
            if implied else ""
        )
        if base is None:
            self._recipe_view.clear(status_html("error", _NO_BASE))
            self._btn_add.disabled = True
            return
        comparison = self.draft()
        self._recipe_view.show(comparison, comparison.problems())
        self._btn_add.disabled = False

    def confirm(self) -> Optional[Comparison]:
        """Add the drafted comparison to the study (and implied values if ticked)."""
        for page in self._visible_pages[:-1]:
            self.page = page
            error = self._page_error()
            if error:
                self._go(page)
                self.status.value = status_html("error", error)
                return None
        self.page = len(_PAGES) - 1
        base, _ = self._base_recipe()
        if base is None:
            self.status.value = status_html("error", _NO_BASE)
            return None
        comparison = self.draft()
        notes: List[str] = []
        if self._components.is_new and comparison.probe:
            self.study.add_component(comparison.probe, self._new_role.value)
            notes.append(
                f"Declared {comparison.probe} ({self._new_role.value}) under System → "
                "Components."
            )
        self.study.upsert_comparison(comparison)
        experiment_type = self.experiment_type
        if experiment_type is not None and experiment_type.implied and self._implied.value:
            self.study.initial_store = with_implied_values(
                self.study.initial_store, experiment_type, comparison.probe
            )
            self.study.notify()
            notes.append(
                "Added to the parameter store (assumed by the experiment type): "
                + ", ".join(f"{i.path} = {i.value:g}" for i in experiment_type.implied) + "."
            )
        self.close()
        self._on_added(comparison, notes)
        return comparison
