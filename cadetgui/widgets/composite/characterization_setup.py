from __future__ import annotations

import html
import json
from typing import Any, Callable, Collection, Dict, List, Optional, Sequence, Union

import ipywidgets as W

from ...cadetprocessadapter import BYPASSABLE_UNITS
from ...characterization_guide import (
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    ChainStepGuide,
    guide_for_step,
    guide_measurements,
    new_step_setup,
    step_type_help,
)
from ...characterization_runner import StepSetup
from ...characterization_stages import STAGES
from ...comparison import Comparison
from ...configuration_store import ConfigurationState, InstrumentState
from ...step_checks import StepStatus, study_steps_status
from ...study import Study
from .._chrome import style_tag
from .._help import determines_table_html, experiments_table_html, term_html
from .._status import status_html
from ._measurement_common import observation_label, system_summary_html
from .system_diagram import recipe_diagram_svg

__all__ = [
    "CharacterizationSetupWidget",
    "step_diagrams_html",
    "components_table_html",
    "runs_use_text",
    "set_up_label",
    "add_custom_step",
]

Navigate = Callable[[str, Dict[str, Any]], None]
FittedSteps = Union[Collection[str], Callable[[], Collection[str]]]

ADD_MEASUREMENT = "Add measurement for this step"
ADD_ANOTHER = "Add another measurement"
SET_UP = "Set up this step"
OPEN_STEP = "Open step"
TRANSFER = "Transfer species…"


def set_up_label(n_measurements: int) -> str:
    """Return the "Set up this step" button label naming how many measurements it fits."""
    plural = "s" if n_measurements != 1 else ""
    return f"{SET_UP} ({n_measurements} measurement{plural})"


def runs_use_text(type_id: str) -> str:
    """Return how runs of experiment type `type_id` use the system, in one line."""
    experiment = EXPERIMENT_TYPES[type_id]
    in_line = "column" in experiment.in_line or "column" not in experiment.bypass
    return (
        f"Runs use: {experiment.template_key} · "
        f"{'column in line' if in_line else 'column bypassed'} · read at "
        f"{observation_label(experiment.solution_path)} ({experiment.detector})"
    )


def _runs_use_html(type_ids: Sequence[str]) -> str:
    lines = []
    for type_id in type_ids:
        text = runs_use_text(type_id)
        if len(type_ids) > 1:
            text += f" — {EXPERIMENT_TYPES[type_id].label}"
        lines.append(f"<div class='cadetgui-note'>{html.escape(text)}</div>")
    return "".join(lines)


def _observed_unit(solution_path: Optional[str]) -> Optional[str]:
    return solution_path.split(".")[0] if solution_path else None


def _type_recipe(type_id: str) -> ConfigurationState:
    """Return a recipe carrying only the flow path of experiment type `type_id`, for drawing."""
    experiment = EXPERIMENT_TYPES[type_id]
    return ConfigurationState(
        components=experiment.components("probe"),
        column_key="",
        binding_key=experiment.binding_key,
        template_key=experiment.template_key,
        instrument=InstrumentState(
            include_sample_loop=experiment.sample_loop,
            bypass_units=[u for u in BYPASSABLE_UNITS if u in experiment.bypass],
        ),
    )


def step_diagrams_html(guide: ChainStepGuide, comparisons: Sequence[Comparison] = ()) -> str:
    """Compact flow-path diagrams with `guide.system_units` highlighted.

    One diagram per distinct flow path and observation point of `comparisons`; without
    comparisons, one per experiment type feeding the step.
    """
    drawn: Dict[tuple, tuple] = {}
    for comparison in comparisons:
        unit = _observed_unit(comparison.solution_path)
        instrument = comparison.recipe.instrument
        key = (unit, tuple(sorted(instrument.bypass_units)) if instrument else None)
        if key in drawn:
            continue
        experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
        label = experiment.label if experiment else comparison.name
        drawn[key] = (label, recipe_diagram_svg(
            comparison.recipe, highlight=guide.system_units, observe=unit, compact=True
        ))
    if not drawn:
        for type_id in guide.experiment_types:
            experiment = EXPERIMENT_TYPES[type_id]
            drawn[(type_id,)] = (experiment.label, recipe_diagram_svg(
                _type_recipe(type_id), highlight=guide.system_units,
                observe=_observed_unit(experiment.solution_path), compact=True,
            ))
    cells = "".join(
        f"<div style='flex:1 1 260px;min-width:0'><small>{html.escape(label)}</small>{svg}</div>"
        for label, svg in drawn.values()
    )
    return f"<div style='display:flex;flex-wrap:wrap;gap:12px'>{cells}</div>"


def components_table_html(study: Study) -> str:
    """Return the study's components: name, role and how many measurements use each."""
    if not study.components:
        return (
            "<p><em>No " + term_html("component", "components") + " declared yet; add them "
            "under System → Components.</em></p>"
        )
    rows = "".join(
        f"<tr><td><b>{html.escape(c.name)}</b></td><td>{term_html(c.role)}</td>"
        f"<td>{len(study.measurements_using(c.name))}</td></tr>"
        for c in study.components
    )
    return (
        "<b>" + term_html("component", "Components") + "</b>"
        "<table class='cadetgui-info-table'><tr><th>Name</th><th>Role</th>"
        f"<th>Used by measurements</th></tr>{rows}</table>"
    )


def add_custom_step(study: Study, name: str = "", stage: Optional[str] = None) -> str:
    """Append a step outside the chain to `study` (auto-named when `name` is blank).

    Returns the new step's name; raises ValueError if a step of that name exists.
    """
    names = {s.name for s in study.steps}
    name = name.strip()
    if not name:
        n = len(names) + 1
        while f"step_{n}" in names:
            n += 1
        name = f"step_{n}"
    if name in names:
        raise ValueError(f"A step called {name!r} already exists.")
    study.upsert_step(StepSetup(name=name, stage=stage or next(iter(STAGES))))
    return name


def _chip(status: Optional[StepStatus]) -> str:
    if status is None:
        return status_html("info", "not started")
    if status.accepted:
        return status_html("ok", "accepted")
    if status.fitted:
        return status_html("info", "fitted, choose a candidate")
    if not status.measurements:
        return status_html("warn", "missing data")
    if status.ready:
        return status_html("ok", "ready to fit")
    return status_html("warn", "needs attention")


class CharacterizationSetupWidget:
    """One card per step of the recommended chain (`DEFAULT_CHAIN`), in lab order.

    Each card says which part of the system the step characterizes (highlighted on the
    flow path), which experiments to run, which measurements are attached, where the step
    stands and what to do next, with one button for that next action. A chain step not
    in the study offers "Add measurement for this step" until a measurement of its
    experiment types exists, then "Set up this step (N measurements)" plus the secondary
    "Add another measurement" (`secondary_buttons`). Study steps that follow no chain
    guide get a card after the chain.

    `on_navigate(target, context)` is called for actions that lead elsewhere:
    `("measurements", {"step_id": guide_id})`, `("step", {"name": step_name})` and
    `("guide", {})`. `fitted_steps` names the steps with a fit result waiting for a
    choice (or is a callable returning them). With `auto_refresh=False` study changes
    only mark the cards stale and the owner calls `refresh()`.
    """

    def __init__(
        self,
        study: Study,
        *,
        on_navigate: Optional[Navigate] = None,
        fitted_steps: FittedSteps = (),
        auto_refresh: bool = True,
        system: Optional[Callable[[], Optional[ConfigurationState]]] = None,
    ) -> None:
        self.study = study
        self._system = system
        self._system_card = W.VBox()
        self.on_navigate = on_navigate
        self._fitted_steps = fitted_steps
        self._auto_refresh = auto_refresh
        self._key: Optional[str] = None
        self.stale = True
        self.statuses: Dict[str, StepStatus] = {}
        self.buttons: Dict[str, W.Button] = {}
        self.secondary_buttons: Dict[str, W.Button] = {}
        self.details: Dict[str, W.VBox] = {}
        self._toggled: Dict[str, bool] = {}
        self._current: Optional[str] = None

        self._cards = W.VBox()
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")
        self._btn_guide = W.Button(description="How it works", icon="question-circle")
        self._btn_guide.on_click(lambda _b: self._navigate("guide", {}))
        intro = W.HTML(
            "<small>Work from top to bottom: each step fits one part of your system to "
            "your " + term_html("measurement", "measurements") + ".</small>"
        )
        self._new_step_name = W.Text(
            description="Name:", placeholder="optional", continuous_update=False
        )
        self._new_step_stage = W.Dropdown(
            description="Step type:", options=[(s.label, s.id) for s in STAGES.values()],
            style={"description_width": "initial"}, layout=W.Layout(width="auto"),
        )
        self._new_step_help = W.HTML()
        self._new_step_stage.observe(lambda _c: self._refresh_new_step_help(), names="value")
        self._refresh_new_step_help()
        self._btn_add_step = W.Button(description="Add custom step", icon="plus")
        self._btn_add_step.on_click(lambda _b: self._on_add_step())
        self.custom_step_status = W.HTML()
        self.custom_step_status.add_class("cadetgui-status")
        add_row = W.HBox(
            [self._new_step_name, self._new_step_stage, self._btn_add_step],
            layout=W.Layout(flex_flow="row wrap"),
        )
        add_row.add_class("cadetgui-toolbar")
        self._custom_step = W.Accordion([W.VBox([
            W.HTML("<small>A step outside the recommended chain, with no measurements "
                   "yet. You pick its step type and measurements on its page.</small>"),
            add_row,
            self._new_step_help,
            self.custom_step_status,
        ])])
        self._custom_step.set_title(0, "Advanced: add a custom step")
        self._custom_step.selected_index = None

        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HBox([
                W.HTML("<div class='cadetgui-panel-title'>Setup</div>"),
                self._btn_guide,
            ], layout=W.Layout(justify_content="space-between", align_items="center")),
            intro,
            self.status,
            self._system_card,
            self._cards,
            self._custom_step,
        ])
        self.root.add_class("cadetgui-panel")

        self.refresh()
        study.add_listener(self._on_study_change)

    @property
    def fitted_steps(self) -> Collection[str]:
        """Steps with a fit result waiting for a choice."""
        fitted = self._fitted_steps
        return fitted() if callable(fitted) else fitted

    def _on_study_change(self) -> None:
        self.stale = True
        if self._auto_refresh:
            self.refresh()

    def _state_key(self, fitted: Collection[str]) -> str:
        study = self.study
        return json.dumps([
            [s.to_dict() for s in study.steps],
            [[c.to_dict(), id(c.run)] for c in study.comparisons],
            id(study.initial_store),
            {name: id(store) for name, store in study.posteriors.items()},
            [[c.name, c.role] for c in study.components],
            sorted(fitted),
        ], sort_keys=True, default=str)

    def refresh(self, *, force: bool = False) -> None:
        """Rebuild the cards from the study; skipped when nothing relevant changed."""
        fitted = set(self.fitted_steps)
        key = self._state_key(fitted)
        self.stale = False
        if key == self._key and not force:
            return
        self._key = key
        self.refresh_system()
        statuses = study_steps_status(self.study, fitted)
        by_step = {s.name: s for s in self.study.steps}
        self.statuses = {s.step_name: s for s in statuses}

        placed: Dict[str, str] = {}
        for status in statuses:
            if status.guide is not None and status.guide.id not in placed:
                placed[status.guide.id] = status.step_name

        self.buttons = {k: v for k, v in self.buttons.items() if k == "system"}
        self.secondary_buttons = {}
        self.details = {}
        accepted = {s.guide.id for s in statuses if s.guide is not None and s.accepted}
        self._current = next((g.id for g in DEFAULT_CHAIN if g.id not in accepted), None)
        cards = []
        for number, guide in enumerate(DEFAULT_CHAIN, start=1):
            step_name = placed.get(guide.id)
            status = self.statuses.get(step_name) if step_name else None
            step = by_step.get(step_name) if step_name else None
            cards.append(self._card(number, guide, status, step))
        for status in statuses:
            if status.step_name not in placed.values():
                cards.append(self._custom_card(status))
        self._cards.children = cards

    def refresh_system(self) -> None:
        """Redraw the "Your system" card from the `system` callable; hidden without one."""
        recipe = self._system() if self._system is not None else None
        if recipe is None:
            self._system_card.children = ()
            return
        others = [c.name for c in self.study.comparisons
                  if c.recipe.column_key != recipe.column_key]
        note = (
            status_html(
                "warn",
                f"{len(others)} measurement(s) were added with a different column model: "
                f"{', '.join(others)}. They keep the setup they were added with.",
            ) if others else ""
        )
        button = W.Button(description="Edit system", icon="sliders", button_style="primary",
                          layout=W.Layout(width="auto"))
        button.on_click(lambda _b: self._navigate("system", {}))
        self.buttons["system"] = button
        body = W.HTML(
            "<p>Every new measurement starts from this system.</p>"
            + recipe_diagram_svg(recipe, compact=False)
            + system_summary_html(recipe)
            + components_table_html(self.study)
            + note
        )
        card = W.VBox([
            W.HBox([
                W.HTML("<div class='cadetgui-section-title'>0. Your system</div>"), button,
            ], layout=W.Layout(justify_content="space-between", align_items="center")),
            body,
        ])
        card.add_class("cadetgui-panel")
        card.add_class("cadetgui-section")
        self._system_card.children = (card,)

    def _tagged(self, guide: ChainStepGuide) -> List[Comparison]:
        return guide_measurements(self.study, guide)

    def _card(
        self,
        number: int,
        guide: ChainStepGuide,
        status: Optional[StepStatus],
        step: Any,
    ) -> W.VBox:
        tagged = self._tagged(guide)
        attached = step.comparisons if step is not None else tagged
        attached_by_type = {
            type_id: [c.name for c in attached if c.experiment_type == type_id]
            for type_id in guide.experiment_types
        }
        body = [
            f"<p>{html.escape(guide.purpose)}</p>",
            "<b>Determines</b>" + determines_table_html(guide.determines),
            "<b>Experiments to run</b>"
            + experiments_table_html(guide.experiment_types, attached_by_type)
            + _runs_use_html(guide.experiment_types),
        ]
        buttons = []
        if status is None and tagged:
            next_action = "Set up this step (add further runs first if you have them)."
            buttons = [
                self._button(
                    guide.id, set_up_label(len(tagged)), "plus", lambda: self.set_up(guide.id)
                ),
                self._button(
                    guide.id, ADD_ANOTHER, "upload",
                    lambda: self._add_measurement(guide.id), primary=False,
                ),
            ]
        elif status is None:
            labels = [EXPERIMENT_TYPES[t].label for t in guide.experiment_types]
            next_action = f"Add a measurement for this step first ({' or '.join(labels)})."
            buttons = [self._button(
                guide.id, ADD_MEASUREMENT, "plus", lambda: self._add_measurement(guide.id)
            )]
        else:
            next_action = status.next_action
            body.append(self._problems_html(status))
            buttons = [self._action_button(guide, status, step)]

        details = W.VBox([
            W.HTML("".join(body)), W.HTML(step_diagrams_html(guide, attached)),
        ])
        return self._collapsible(
            guide.id, f"{number}. {guide.title}", status, buttons, next_action, details,
            open_=guide.id == self._current,
        )

    def _collapsible(
        self, key: str, title: str, status: Optional[StepStatus], buttons: List[W.Button],
        next_action: str, details: W.VBox, *, open_: bool,
    ) -> W.VBox:
        """Return a card showing title, status, next action and buttons, details on demand."""
        shown = self._toggled.get(key, open_)
        details.layout.display = "" if shown else "none"
        toggle = W.Button(
            icon="chevron-down" if shown else "chevron-right", tooltip="Show or hide details",
            layout=W.Layout(width="32px"),
        )

        def on_toggle(_b: Any) -> None:
            now = details.layout.display == "none"
            details.layout.display = "" if now else "none"
            toggle.icon = "chevron-down" if now else "chevron-right"
            self._toggled[key] = now

        toggle.on_click(on_toggle)
        self.details[key] = details
        header = W.HBox([
            W.HBox([toggle, W.HTML(
                f"<div class='cadetgui-section-title'>{html.escape(title)} {_chip(status)}</div>"
            )], layout=W.Layout(align_items="center")),
            W.HBox(buttons),
        ], layout=W.Layout(
            justify_content="space-between", align_items="center", flex_flow="row wrap",
        ))
        card = W.VBox([header, W.HTML(f"<b>Next:</b> {html.escape(next_action)}"), details])
        card.add_class("cadetgui-section")
        return card

    def _custom_card(self, status: StepStatus) -> W.VBox:
        name = status.step_name
        button = self._button(name, OPEN_STEP, "arrow-right", lambda: self._open(name))
        details = W.VBox([W.HTML(
            "<small>A step outside the recommended chain.</small>" + self._problems_html(status)
        )])
        return self._collapsible(
            name, name, status, [button], status.next_action, details, open_=False
        )

    @staticmethod
    def _problems_html(status: StepStatus) -> str:
        if not status.problems or status.accepted:
            return ""
        return "".join(status_html("warn", p) + "<br>" for p in status.problems)

    def _action_button(self, guide: ChainStepGuide, status: StepStatus, step: Any) -> W.Button:
        name = status.step_name
        if status.accepted:
            return self._button(guide.id, OPEN_STEP, "arrow-right", lambda: self._open(name))
        if not step.comparisons and not self._tagged(guide):
            return self._button(
                guide.id, ADD_MEASUREMENT, "plus", lambda: self._add_measurement(guide.id)
            )
        open_ids = [c.id for c in status.open_checks]
        if open_ids and all(i == "species_gaps" for i in open_ids):
            return self._button(guide.id, TRANSFER, "share", lambda: self._open(name))
        return self._button(guide.id, OPEN_STEP, "arrow-right", lambda: self._open(name))

    def _button(
        self, key: str, label: str, icon: str, action: Callable[[], None], *,
        primary: bool = True,
    ) -> W.Button:
        button = W.Button(
            description=label, icon=icon, button_style="primary" if primary else "",
            layout=W.Layout(width="auto"),
        )
        button.on_click(lambda _b: action())
        (self.buttons if primary else self.secondary_buttons)[key] = button
        return button

    def _navigate(self, target: str, context: Dict[str, Any]) -> None:
        if self.on_navigate is not None:
            self.on_navigate(target, context)

    def _open(self, step_name: str) -> None:
        self._navigate("step", {"name": step_name})

    def _add_measurement(self, step_id: str) -> None:
        self._navigate("measurements", {"step_id": step_id})

    def set_up(self, guide_id: str) -> str:
        """Add the chain step `guide_id` to the study with its tagged measurements.

        The step is placed after the study steps that come before it in the chain.
        Returns the new step's name.
        """
        guide = next(g for g in DEFAULT_CHAIN if g.id == guide_id)
        try:
            setup = new_step_setup(guide, self._tagged(guide))
        except ValueError as exc:
            self.status.value = status_html("error", str(exc))
            return ""
        if setup.name in {s.name for s in self.study.steps}:
            self.status.value = status_html("error", f"A step called {setup.name!r} exists.")
            return ""
        order = [g.id for g in DEFAULT_CHAIN]
        position = order.index(guide.id)
        index = len(self.study.steps)
        for i, step in enumerate(self.study.steps):
            other = guide_for_step(step)
            if other is not None and order.index(other.id) > position:
                index = i
                break
        if index == len(self.study.steps):
            self.study.upsert_step(setup)
        else:
            self.study.steps.insert(index, setup)
            self.study.notify()
        self.status.value = status_html("ok", f"Set up {guide.title}.")
        self._open(setup.name)
        return setup.name

    def add_step(self, name: str = "", stage: Optional[str] = None) -> str:
        """Append a step outside the chain (see `add_custom_step`) and open it."""
        name = add_custom_step(self.study, name, stage)
        self._open(name)
        return name

    def _refresh_new_step_help(self) -> None:
        text = step_type_help(self._new_step_stage.value)
        self._new_step_help.value = f"<small>{html.escape(text)}</small>" if text else ""

    def _on_add_step(self) -> None:
        try:
            name = self.add_step(self._new_step_name.value, self._new_step_stage.value)
        except ValueError as exc:
            self.custom_step_status.value = status_html("error", str(exc))
            return
        self._new_step_name.value = ""
        self.custom_step_status.value = status_html("ok", f"Added {name}.")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
