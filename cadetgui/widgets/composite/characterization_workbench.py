from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import ipywidgets as W

from ...characterization_guide import guide_for_step
from ...configuration_store import ConfigurationState
from ...step_checks import study_steps_status
from ...study import Study
from ..shell import (
    SYSTEM_GROUP,
    SidebarShell,
    collect_panes,
    resolve_step,
    system_pane_label,
    validate_steps,
)
from .bench import bench_root
from .characterization_guide_pane import CharacterizationGuideWidget
from .characterization_setup import CharacterizationSetupWidget, add_custom_step
from .characterization_step import CharacterizationStepWidget
from .comparisons import ComparisonsWidget
from .configuration import ConfigurationWidget
from .flow_rate import FlowRateSection
from .instrument import InstrumentWidget
from .parameter_store_view import ParameterStoreWidget, chain_warnings

__all__ = ["CharacterizationWorkbenchWidget"]

SETUP = "Setup"
SYSTEM = SYSTEM_GROUP
PROCESS = "Advanced configuration"
MEASUREMENTS = "Measurements"
STEPS = "Characterization steps"
PARAMETERS = "Parameters"
GUIDE = "Guide"
SYSTEM_PANE = system_pane_label("Instrument")
PROCESS_PANE = system_pane_label(PROCESS)
CONFIGURATION_INTRO = (
    "In characterization these settings are the starting point of every new measurement: "
    "the column geometry, starting guesses for the values the characterization steps "
    "determine (porosities, dispersion, film diffusion) and the binding model parameters. "
    "Each measurement keeps its own copy; accepted fit results replace the guesses. The "
    "process (method) of a run is not set here: it comes with the measurement's experiment "
    "type."
)
_FLOW_RATE_NOTE = (
    "The flow rate your runs use. Every new measurement starts with it; a run that used "
    "another flow rate keeps its own, entered when you add it."
)
_PANES = (SETUP, SYSTEM, PROCESS, MEASUREMENTS, STEPS, PARAMETERS, GUIDE)


def step_pane(name: str) -> str:
    """Sidebar label of the pane for the step called `name`."""
    return f"{STEPS}: {name}"


class CharacterizationWorkbenchWidget:
    """Sidebar workbench over one characterization `Study`.

    Panes: "Setup" (one card per chain step with its next action; sets up steps),
    "System" (instrument with the study's components and a `FlowRateSection`; the
    "Advanced configuration" sub-pane holds column and binding settings, the base recipe
    of new measurements), "Measurements", "Characterization steps" (one
    `CharacterizationStepWidget` per study step, following the study live), "Parameters"
    (the store; saves and loads the study) and "Guide". Sidebar warnings come from
    `study_steps_status`, the same checks the step pages and the Setup pane show.

    `include` narrows the panes to a subset of `_PANES`; an excluded pane's widget is
    neither constructed nor wired and its attribute (`.setup`, `.comparisons`,
    `.parameters`, `.guide`; `.steps` stays empty) is None. The instrument and
    configuration are always built, since they hold the base recipe of every new
    measurement. Without `instrument`/`configuration`, defaults are seeded (all units and
    the sample loop in the flow path; process template hidden, LRMP column with SMA
    binding); passed-in widgets are only bound to the study.

    `navigate(target, context)` switches panes: `"measurements"` (`step_id` and/or
    `experiment_type` open the add stepper, `select` shows a measurement), `"step"`
    (`name`), `"setup"`, `"system"` (`unit` expands the hardware and highlights it),
    `"parameters"`, `"guide"`. Opening a step highlights the units it characterizes.
    """

    def __init__(
        self,
        *,
        study: Optional[Study] = None,
        include: Optional[Sequence[str]] = None,
        instrument: Optional[InstrumentWidget] = None,
        configuration: Optional[ConfigurationWidget] = None,
    ) -> None:
        if include is None:
            include = _PANES
        validate_steps(include, _PANES)
        self._include = tuple(dict.fromkeys(include))
        self.study = study if study is not None else Study()

        self.instrument = instrument
        if self.instrument is None:
            self.instrument = InstrumentWidget(hardware_expanded=True, hardware_only=True)
            self.instrument.apply_state(dataclasses.replace(
                self.instrument.snapshot(), include_sample_loop=True, bypass_units=[]
            ))

        self.configuration = configuration
        if self.configuration is None:
            self.configuration = ConfigurationWidget(
                instrument=self.instrument, workspace_header=False,
                show_process_template=False, intro=CONFIGURATION_INTRO,
            )
            self.configuration.select_models(
                template="Pulse Injection",
                column="Lumped Rate Model With Pores (LRMP)",
                binding="Steric Mass Action (SMA)",
            )

        self.instrument.bind_study(self.study)
        self.components = self.instrument.study_components
        self.flow_rate = FlowRateSection(self.configuration, note=_FLOW_RATE_NOTE)
        self.instrument.add_section(self.flow_rate.root, after_components=True)

        def pane(label: str, factory: Callable[[], Any]) -> Any:
            return resolve_step(label, None, steps=self._include, factory=factory)

        self.comparisons = pane(MEASUREMENTS, lambda: ComparisonsWidget(
            self.study, configuration=self.configuration
        ))
        self.parameters = pane(PARAMETERS, lambda: ParameterStoreWidget(self.study))
        self.guide = pane(GUIDE, CharacterizationGuideWidget)
        self._step_widgets: List[CharacterizationStepWidget] = []
        self.setup = pane(SETUP, lambda: CharacterizationSetupWidget(
            self.study, on_navigate=self.navigate,
            fitted_steps=lambda: self.fitted_steps, auto_refresh=False,
            system=self._system_state,
        ))

        self._shell = SidebarShell(self._panes(), groups=self._groups())
        self._nav = self._shell.nav
        self._shell.add_show_listener(lambda _label: self._on_pane_shown())
        self._sync_steps()

        self.study.add_listener(self._on_study_change)
        self.configuration.add_listener(self._refresh_status)
        if self.setup is not None:
            self.configuration.add_listener(lambda *_: self.setup.refresh_system())
        self._refresh_status()

        self.root = bench_root("Characterization", self._shell, self.configuration)

    @classmethod
    def from_file(cls, path: "Path | str", **kwargs: Any) -> "CharacterizationWorkbenchWidget":
        """Open the study file at `path` (see `Study.load`); `kwargs` go to the constructor."""
        return cls(study=Study.load(path), **kwargs)

    @property
    def steps(self) -> Dict[str, CharacterizationStepWidget]:
        """Step widgets by step name, in chain order."""
        return {w.step_name: w for w in self._step_widgets}

    @property
    def fitted_steps(self) -> Set[str]:
        """Steps whose widget holds a fit result that was not accepted."""
        return {
            w.step_name for w in self._step_widgets if w.result is not None and not w.accepted
        }

    def navigate(self, target: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Show the pane for `target` (see the class docstring); excluded panes are ignored."""
        context = context or {}
        labels: Dict[str, Callable[[], Optional[str]]] = {
            "setup": lambda: SETUP,
            "system": lambda: SYSTEM_PANE,
            "measurements": lambda: MEASUREMENTS,
            "step": lambda: step_pane(context["name"]),
            "parameters": lambda: PARAMETERS,
            "guide": lambda: GUIDE,
        }
        if target not in labels:
            raise ValueError(f"Unknown navigation target {target!r}.")
        label = labels[target]()
        if label not in self._shell.panes:
            return
        if target == "step":
            self._highlight_step(context["name"])
        self._shell.show(label)
        if target == "system" and context.get("unit"):
            self.instrument.set_hardware_expanded(True)
            self.instrument.set_highlight((context["unit"],))
        step_id, type_id = context.get("step_id"), context.get("experiment_type")
        if target == "measurements" and context.get("select"):
            self.comparisons.select(context["select"])
        if target == "measurements" and (step_id or type_id):
            self.comparisons.start_add(step_id=step_id, experiment_type=type_id)

    def _system_state(self) -> Optional[ConfigurationState]:
        """Return the current System setup as a recipe, or None while nothing valid is built."""
        try:
            return self.configuration.snapshot()
        except RuntimeError:
            return None

    def _on_pane_shown(self) -> None:
        current = self._shell.current
        if current == SETUP:
            self.setup.refresh()
        for widget in self._step_widgets:
            if current == step_pane(widget.step_name):
                self._highlight_step(widget.step_name)

    def _highlight_step(self, step_name: str) -> None:
        setup = next((s for s in self.study.steps if s.name == step_name), None)
        if setup is None:
            return
        guide = guide_for_step(setup)
        observe = next(
            (c.solution_path.split(".")[0] for c in setup.comparisons if c.solution_path), None
        )
        self.instrument.set_highlight(guide.system_units if guide else (), observe)

    def add_step(
        self, name: str = "", stage: Optional[str] = None
    ) -> Optional[CharacterizationStepWidget]:
        """Append a custom step to the study (see `add_custom_step`) and open its pane.

        Returns the new step's widget, or None when the "Steps" panes are not included.
        """
        name = add_custom_step(self.study, name, stage)
        self.navigate("step", {"name": name})
        return self.steps.get(name)

    def _panes(self) -> List[Tuple[str, W.Widget]]:
        slots: Dict[str, Any] = {
            SETUP: self.setup,
            SYSTEM_PANE: self.instrument if SYSTEM in self._include else None,
            PROCESS_PANE: self.configuration if PROCESS in self._include else None,
            MEASUREMENTS: self.comparisons,
            **{step_pane(w.step_name): w for w in self._step_widgets},
            PARAMETERS: self.parameters,
            GUIDE: self.guide,
        }
        return [(label, widget.root) for label, widget in collect_panes(list(slots), slots)]

    def _groups(self) -> Dict[str, List[str]]:
        return {
            SYSTEM: [SYSTEM_PANE, PROCESS_PANE],
            STEPS: [step_pane(w.step_name) for w in self._step_widgets],
        }

    def _sync_steps(self) -> None:
        """Match the step widgets to `study.steps`: add, drop and reorder, then re-lay panes."""
        if STEPS not in self._include:
            return
        by_name = {w.step_name: w for w in self._step_widgets}
        widgets = []
        for setup in self.study.steps:
            widget = by_name.pop(setup.name, None)
            if widget is None:
                widget = CharacterizationStepWidget(
                    self.study, setup.name, on_navigate=self.navigate
                )
                widget.add_listener(self._refresh_status)
            widgets.append(widget)
        for stale in by_name.values():
            stale.close()
        self._step_widgets = widgets

        panes = self._panes()
        current = [(label, id(widget)) for label, widget in panes]
        shown = [(label, id(self._shell.panes[label])) for label in self._shell.order]
        if current != shown:
            selected = self._shell.panes.get(self._shell.current)
            show = next((label for label, widget in panes if widget is selected), None)
            self._shell.set_panes(panes, groups=self._groups(), show=show)

    def _on_study_change(self) -> None:
        self._sync_steps()
        self._refresh_status()

    def _set_warning(self, label: str, message: Optional[str]) -> None:
        if label in self._shell.panes:
            self._shell.set_warning(label, message)

    def _refresh_status(self, *_args: object) -> None:
        """Flag panes that can't do anything useful yet, without blocking navigation."""
        config_problem = self.configuration.name_error("running a simulation")
        if not self.configuration.show_process_template:
            if config_problem is None and self._system_state() is None:
                config_problem = "The column or binding settings are incomplete."
        elif config_problem is None and self.configuration.process is None:
            config_problem = "No valid process is built yet."
        self._set_warning(PROCESS_PANE, config_problem)

        problems = {
            c.name: found for c in self.study.comparisons
            if (found := self.study.measurement_problems(c))
        }
        self._set_warning(MEASUREMENTS, "\n".join(
            f"{name}: {' '.join(found)}" for name, found in problems.items()
        ) or None)
        for status in study_steps_status(self.study, self.fitted_steps):
            message = None if status.accepted else "\n".join(status.problems)
            self._set_warning(step_pane(status.step_name), message or None)
        self._set_warning(PARAMETERS, "\n".join(chain_warnings(self.study)) or None)
        if self._shell.current == SETUP:
            self.setup.refresh()

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
