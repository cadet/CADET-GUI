from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
import numpy as np

from ... import characterization_runner
from ...characterization_guide import ChainStepGuide, guide_for_step, starting_values
from ...characterization_runner import (
    AVERAGE_TAG,
    Candidate,
    StepResult,
    StepSetup,
    fitted_variables,
)
from ...characterization_stages import STAGES, describe_stage
from ...parameter_store import (
    ParameterStore,
    Step,
    missing_requirements,
    transfer_species,
)
from ...step_checks import (
    CONFIRM_KNOWN,
    CONFIRMED_DEFAULT,
    KNOWN_HARDWARE,
    RECORD_ASSUMPTIONS,
    TRANSFER,
    StepCheck,
    confirm_known_value,
    known_value_label,
    missing_assumptions,
    record_assumptions,
    step_checks,
)
from ...study import Study
from .._chrome import style_tag
from .._help import (
    determines_table_html,
    experiments_table_html,
    info_box_html,
    term_html,
)
from .._status import status_html
from ._step_results import _CandidateResults
from ._step_run import _StepRun
from ._step_setup_form import _StepSetupForm, _unit_html
from .characterization_setup import step_diagrams_html

__all__ = ["CharacterizationStepWidget"]


def _missing(setup: StepSetup, store: ParameterStore) -> List[str]:
    """`setup.requires` absent from `store`; unlike `setup.step`, works with invalid options."""
    return missing_requirements(Step(setup.name, requires=tuple(setup.requires)), store)


def _components_html(study: Study, setup: StepSetup) -> str:
    """Return a line naming the components this step's measurements use, with roles."""
    names = list(dict.fromkeys(c.probe for c in setup.comparisons if c.probe))
    if not names:
        return ""
    parts = []
    for name in names:
        component = study.component(name)
        role = f" ({component.role})" if component is not None else " (not declared)"
        parts.append(html.escape(name + role))
    return (
        "<p><b>" + term_html("component", "Components") + ":</b> " + ", ".join(parts)
        + ". <small>Values this step fits are stored under these names; a later step "
        "reuses them only for the same component.</small></p>"
    )


def _header_html(
    guide: ChainStepGuide, setup: StepSetup, *, open: bool, components: str = ""
) -> str:
    """Return the step's lab-language description: purpose, experiments, advice."""
    body = (
        f"<p>{html.escape(guide.purpose)}</p>"
        + components +
        f"<b>Determines</b>{determines_table_html(guide.determines)}"
        f"<b>Experiments that feed it</b>{experiments_table_html(guide.experiment_types)}"
        + "<p><small>Lab checks the software cannot do for this step are in the Guide."
        "</small></p>"
        + info_box_html("Reading the results", f"<p>{html.escape(guide.reading_results)}</p>")
        + step_diagrams_html(guide, setup.comparisons)
    )
    return info_box_html(f"About this step: {guide.title}", body, open=open)


Navigate = Callable[[str, Dict[str, Any]], None]


def _best_values_html(
    names: List[str], units: Dict[str, str], candidate: Candidate, setup: StepSetup
) -> str:
    """Return a candidate's variable values and objectives as two tables."""
    if len(names) != len(candidate.x):
        names = [f"x{i + 1}" for i in range(len(candidate.x))]
    variables = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{value:.4g}</td>"
        f"<td>{_unit_html(units.get(name, ''))}</td></tr>"
        for name, value in zip(names, candidate.x)
    )
    objectives = "".join(
        f"<tr><td>{html.escape(c.name)}</td><td>{value:.4g}</td>"
        f"<td>{term_html(c.metric)}</td></tr>"
        for c, value in zip(setup.comparisons, candidate.f)
    )
    return (
        f"<div><b>{term_html('best average', 'Best average')} of the final front</b></div>"
        "<div style='display:flex;flex-wrap:wrap;gap:24px'>"
        "<table class='cadetgui-info-table'><tr><th>Parameter</th><th>Value</th>"
        f"<th>Unit</th></tr>{variables}</table>"
        "<table class='cadetgui-info-table'><tr><th>Measurement</th><th>Error</th>"
        f"<th>Metric</th></tr>{objectives}</table></div>"
    )


class CharacterizationStepWidget(_StepRun):
    """Set up, run and accept one characterization step of a `Study`.

    Every setup edit is written to the study with `Study.upsert_step`. A chain step
    lists the measurements that feed it, all included unless unticked; new fitting
    measurements are included when they are added. "Before you run" shows live checks
    (`step_checks.step_checks`), each open one with its fix; a hardware value left at its
    default offers "Use this value" (with an editable value) and "Edit in System". A run
    fits the step type's `Characterize*` class on a background thread; the live fit plot
    simulates the current best-average candidate on separately built processes, at most
    once per generation. Pareto candidates are
    previewed against every comparison, and only "Accept candidate" writes a posterior
    (`Study.accept`). The setup is read-only while running or showing a result until
    "Edit setup" is clicked.

    `on_navigate(target, context)` is called for fixes that lead elsewhere, with the
    targets of `CharacterizationWorkbenchWidget.navigate`: `("measurements", {"step_id"})`,
    `("measurements", {"select": name})`, `("step", {"name"})`, `("system", {"unit"})`,
    `("parameters", {})`. Without it those buttons are hidden.
    """

    def __init__(
        self,
        study: Study,
        step_name: Optional[str] = None,
        *,
        on_navigate: Optional[Navigate] = None,
    ) -> None:
        self.study = study
        self.on_navigate = on_navigate
        self._listeners: List[Callable[[], None]] = []
        self._committing = False
        self._run_names: List[str] = []
        self._run_units: Dict[str, str] = {}
        self.accepted = False
        self._running = False
        self._checks_key: Optional[tuple] = None
        self.checks: List[StepCheck] = []
        self._known_fields: Dict[str, W.FloatText] = {}
        self._init_run()

        existing = next((s for s in study.steps if s.name == step_name), None)
        if existing is None:
            name = step_name or self._free_name()
            existing = StepSetup(name=name, stage=next(iter(STAGES)))
        self._name = existing.name
        self._committed: Optional[StepSetup] = (
            existing if any(s is existing for s in study.steps) else None
        )

        self.form = _StepSetupForm(
            study, self._on_form_change,
            on_add_measurement=(
                (lambda step_id: self._navigate("measurements", {"step_id": step_id}))
                if on_navigate is not None else None
            ),
        )
        self.results = _CandidateResults(self._accept)

        self._warnings = W.HTML()
        self._checks_box = W.VBox()
        self._gaps = W.HTML()
        self._btn_transfer = W.Button(
            description="Transfer to this step's species", icon="share",
            layout=W.Layout(display="none", width="auto"),
        )
        self._btn_transfer.on_click(lambda _b: self._transfer_clicked())
        self._btn_edit = W.Button(
            description="Edit setup", icon="pencil", layout=W.Layout(display="none")
        )
        self._btn_edit.on_click(lambda _b: self.edit_setup())
        self._lock_note = W.HTML(
            "<small>Locked while a fit result is shown. Edit setup unlocks it and discards "
            "a result that is not accepted yet; accepted values stay in the parameter "
            "store.</small>",
            layout=W.Layout(display="none"),
        )
        self._btn_run = W.Button(description="Run step", icon="play", button_style="success")
        self._btn_run.on_click(lambda _b: self.start_run())
        self._best_values = W.HTML()
        self.status = W.HTML("<em>Ready.</em>")
        self.status.add_class("cadetgui-status")

        self.header = W.HTML()
        header_box = W.VBox([self.header])
        header_box.add_class("cadetgui-panel")
        header_box.add_class("cadetgui-section")
        self._header_box = header_box
        setup_box = W.VBox([
            W.HBox([
                W.HTML("<div class='cadetgui-panel-title'>Setup</div>"), self._btn_edit,
            ], layout=W.Layout(justify_content="space-between", align_items="center")),
            self._lock_note,
            W.HTML(
                f"<small>The fit starts from this step's {term_html('prior')}: the values "
                "accepted before it.</small>"
            ),
            W.HTML("<div class='cadetgui-section-title'>Before you run</div>"),
            self._checks_box,
            self.form.root,
            self._warnings,
        ])
        setup_box.add_class("cadetgui-panel")
        setup_box.add_class("cadetgui-section")
        run_box = W.VBox([
            W.HTML("<div class='cadetgui-panel-title'>Run</div>"),
            W.HBox(
                [self._btn_run, self._btn_cancel, self.live_plot, self._progress_label],
                layout=W.Layout(flex_flow="row wrap", align_items="center"),
            ),
            self._progress_box,
            self._live_note,
            self.status,
        ])
        run_box.add_class("cadetgui-panel")
        run_box.add_class("cadetgui-section")
        results_box = W.VBox([
            W.HTML("<div class='cadetgui-panel-title'>Results</div>"),
            W.HTML(
                "<small>Accepting a candidate writes its values as this step's "
                f"{term_html('posterior')} into the parameter store.</small>"
            ),
            self._best_values,
            self.results.root,
        ])
        results_box.add_class("cadetgui-panel")
        results_box.add_class("cadetgui-section")
        self.root = W.VBox([W.HTML(style_tag()), header_box, setup_box, run_box, results_box])

        self.form.set_setup(existing)
        self._refresh_warnings()
        study.add_listener(self._on_study_change)

    def _free_name(self) -> str:
        names = {s.name for s in self.study.steps}
        n = len(names) + 1
        while f"step_{n}" in names:
            n += 1
        return f"step_{n}"

    @property
    def step_name(self) -> str:
        """Name of the step this widget edits."""
        return self._name

    @property
    def running(self) -> bool:
        """Whether a run is in progress."""
        return self._running

    @property
    def result(self) -> Optional[StepResult]:
        """The last finished run's front, until the setup is edited again."""
        return self.results.result

    @property
    def candidates(self) -> List[Candidate]:
        """Candidates offered from the last run."""
        return self.results.candidates

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Call `fn()` after a setup edit, a finished run or an accept."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    def _navigate(self, target: str, context: Dict[str, Any]) -> None:
        if self.on_navigate is not None:
            self.on_navigate(target, context)

    def get_value(self) -> StepSetup:
        """Return the setup the controls currently describe."""
        return self.form.get_setup()

    def _on_form_change(self) -> None:
        setup = self.form.get_setup()
        error = self._commit(setup)
        if error:
            self.status.value = status_html("error", error)
        self._refresh_warnings()
        self._notify()

    def _commit(self, setup: StepSetup) -> Optional[str]:
        if not setup.name:
            return "The step needs a name."
        names = [s.name for s in self.study.steps]
        if setup.name != self._name and setup.name in names:
            return f"Another step is already called {setup.name!r}."
        self._committing = True
        try:
            if setup.name != self._name and self._name in names:
                self.study.steps[names.index(self._name)] = setup
                if self._name in self.study.posteriors:
                    self.study.posteriors[setup.name] = self.study.posteriors.pop(self._name)
                self._name, self._committed = setup.name, setup
                self.study.notify()
            else:
                self._name, self._committed = setup.name, setup
                self.study.upsert_step(setup)
        finally:
            self._committing = False
        return None

    @property
    def _editable(self) -> bool:
        return not self.running and self.result is None

    def _include_new_measurements(self) -> None:
        """Rebuild the measurement rows; commit fitting measurements added to the study."""
        added = self.form.refresh_comparisons(auto_include=self._editable)
        if added:
            self._on_form_change()

    def _on_study_change(self) -> None:
        if self._committing or self.running:
            self._refresh_warnings()
            return
        stored = next((s for s in self.study.steps if s.name == self._name), None)
        if stored is not None and stored is not self._committed:
            changed = self._committed is not None and (
                [c.name for c in stored.comparisons]
                != [c.name for c in self._committed.comparisons]
            )
            self._committed = stored
            self.form.set_setup(stored)
            if changed and self.results.result is not None:
                self.edit_setup()
                self.status.value = status_html(
                    "warn", "The measurements changed, so the fit result was discarded."
                )
        else:
            self._include_new_measurements()
            self.form.refresh_requires(self.form.get_setup())
        if self.results.result is not None:
            self.form.set_locked(True)
        self._refresh_warnings()

    def _prior(self) -> ParameterStore:
        names = [s.name for s in self.study.steps]
        return self.study.prior_for(self._name) if self._name in names else self.study.current_store

    def _setup_problems(self, setup: StepSetup) -> List[str]:
        problems = []
        if not setup.comparisons:
            problems.append("Select at least one measurement.")
        for name, found in self.form.problems_of_selected().items():
            problems.append(f"{name}: " + " ".join(found))
        try:
            describe_stage(setup.stage, **setup.options)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def _refresh_warnings(self) -> None:
        setup = self.form.get_setup()
        try:
            provides = setup.provides
        except ValueError:
            provides = []
        self.form.show_chain(provides)
        lines = []
        if self._name in self.study.posteriors and not self.accepted:
            lines.append(status_html(
                "info", "This step already has an accepted posterior; accepting a new "
                "candidate replaces it.",
            ))
        self._warnings.value = "<br>".join(lines)
        self._refresh_checks(setup)
        self.form.refresh_summary()
        self._refresh_header(setup)

    def _refresh_checks(self, setup: StepSetup) -> None:
        """Recompute the live checks and rebuild their rows when they changed."""
        try:
            checks = step_checks(self.study, setup)
        except Exception as exc:  # noqa: BLE001 -- shown instead of the checks
            checks = [StepCheck("error", "warn", f"The checks could not run: {exc}")]
        editable = self._editable
        key = (tuple(checks), editable, self.on_navigate is not None)
        self.checks = checks
        if key == self._checks_key:
            return
        self._checks_key = key
        gaps = next((c for c in checks if c.id == "species_gaps"), None)
        self._gaps.value = "" if gaps is None else (
            status_html("warn", gaps.text) + " "
            + term_html("species transfer", "(species transfer)")
        )
        self._btn_transfer.layout.display = "" if gaps is not None and editable else "none"
        self._known_fields = {}
        rows = []
        for check in checks:
            if any(action.target == TRANSFER for action in check.actions):
                rows.append(W.HBox(
                    [self._gaps, self._btn_transfer],
                    layout=W.Layout(align_items="center", flex_flow="row wrap"),
                ))
                continue
            controls: List[W.Widget] = [W.HTML(status_html(check.status, check.text))]
            for action in check.actions:
                if action.target == CONFIRM_KNOWN and editable:
                    controls += self._known_value_field(action.context)
                button = self._action_button(action, editable)
                if button is not None:
                    controls.append(button)
            rows.append(W.HBox(
                controls, layout=W.Layout(align_items="center", flex_flow="row wrap"),
            ))
        self._checks_box.children = rows

    def _known_value_field(self, context: Any) -> List[W.Widget]:
        """Return an editable hardware value prefilled with the default, and its unit."""
        field = W.FloatText(
            value=float(f"{context['value'] / context['scale']:.6g}"),
            tooltip="Your hardware value; the default is prefilled.",
            layout=W.Layout(width="110px"),
        )
        self._known_fields[context["path"]] = field
        return [field, W.HTML(html.escape(context["unit"]))]

    def _action_button(self, action: Any, editable: bool) -> Optional[W.Button]:
        local = {
            RECORD_ASSUMPTIONS: self._record_assumptions_clicked,
            CONFIRM_KNOWN: lambda: self._confirm_known_clicked(action.context),
        }
        if action.target in local:
            if not editable:
                return None
            callback = local[action.target]
        elif self.on_navigate is None:
            return None
        else:
            def callback(action: Any = action) -> None:
                self._navigate(action.target, dict(action.context))
        button = W.Button(description=action.label, layout=W.Layout(width="auto"))
        button.on_click(lambda _b: callback())
        return button

    def check_buttons(self) -> Dict[str, W.Button]:
        """Buttons of the open checks by label, for scripting and tests."""
        buttons = {}
        for row in self._checks_box.children:
            for child in row.children:
                if isinstance(child, W.Button) and child.layout.display != "none":
                    buttons[child.description] = child
        return buttons

    @property
    def guide(self) -> Optional[ChainStepGuide]:
        """The chain guide this step follows, if any."""
        return guide_for_step(self.form.get_setup())

    def _refresh_header(self, setup: StepSetup) -> None:
        guide = guide_for_step(setup)
        self._header_box.layout.display = "none" if guide is None else ""
        if guide is None:
            self.header.value = ""
            return
        not_run = (
            self.result is None and not self.running and setup.name not in self.study.posteriors
        )
        value = _header_html(
            guide, setup, open=not_run, components=_components_html(self.study, setup)
        )
        if self.header.value != value:
            self.header.value = value

    def _species_gaps(self, setup: StepSetup) -> Dict[str, List[str]]:
        """Gaps left once the experiment types' assumed values are recorded."""
        prior = self._prior()
        try:
            gaps = characterization_runner.species_gaps(setup, record_assumptions(setup, prior))
        except Exception:  # noqa: BLE001 -- an unbuildable recipe is reported by problems()
            return {}
        return {path: names for path, names in gaps.items() if path in prior}

    def _transfer_clicked(self) -> None:
        try:
            self.transfer_species_gaps()
        except KeyError as exc:
            self.status.value = status_html("error", str(exc.args[0]))

    def _replace_prior(self, store: ParameterStore) -> str:
        """Make `store` the store this step starts from; return where it was written."""
        source = self._prior_step_name()
        if source is None:
            self.study.initial_store = store
            self.study.notify()
        else:
            self.study.accept(source, store)
        return "initial store" if source is None else source

    def transfer_species_gaps(self, note: Optional[str] = None) -> ParameterStore:
        """Copy single-probe species values onto this step's missing species in its prior.

        Values the experiment types assume are left to `record_assumptions`. The
        transferred store replaces the posterior this step starts from (or the initial
        store when no earlier step is accepted), so `Study.prior_for` returns it.
        """
        setup = self.form.get_setup()
        prior = self._prior()
        gaps = self._species_gaps(setup)
        species = list(dict.fromkeys(name for names in gaps.values() for name in names))
        transferred = transfer_species(prior, list(gaps), species, note=note)
        where = self._replace_prior(transferred)
        self.status.value = status_html(
            "ok", f"Transferred {', '.join(gaps)} to {', '.join(species)} ({where}).",
        )
        return transferred

    def _record_assumptions_clicked(self) -> None:
        self.record_assumptions()

    def _confirm_known_clicked(self, context: Any) -> None:
        field = self._known_fields.get(context["path"])
        value = context["value"] if field is None else field.value * context["scale"]
        if not np.isfinite(value) or value <= 0:
            self.status.value = status_html("error", "Enter a positive hardware value.")
            return
        self.confirm_known_value(context["path"], value, default=context["value"])

    def confirm_known_value(
        self, path: str, value: float, *, default: Optional[float] = None
    ) -> ParameterStore:
        """Record `value` of hardware `path` as known (see `step_checks.confirm_known_value`).

        The note is "confirmed default" when `value` equals `default` (or no default is
        given), else "known hardware".
        """
        same = default is None or bool(np.isclose(value, default, rtol=1e-9, atol=0.0))
        store = confirm_known_value(
            self.study, path, value, note=CONFIRMED_DEFAULT if same else KNOWN_HARDWARE
        )
        self.status.value = status_html(
            "ok", f"Recorded the {known_value_label(path).lower()} as known hardware "
            "(starting values).",
        )
        return store

    def record_assumptions(self) -> ParameterStore:
        """Write the values this step's experiment types assume into the store it starts from."""
        store = record_assumptions(self.form.get_setup(), self._prior())
        where = self._replace_prior(store)
        self.status.value = status_html("ok", f"Recorded the assumed values ({where}).")
        return store

    def _prior_step_name(self) -> Optional[str]:
        """Return the accepted step whose posterior `_prior()` is, or None (initial store)."""
        names = [s.name for s in self.study.steps]
        before = names[: names.index(self._name)] if self._name in names else names
        accepted = [n for n in before if n in self.study.posteriors]
        return accepted[-1] if accepted else None

    def _show_edit(self, shown: bool) -> None:
        self._btn_edit.layout.display = self._lock_note.layout.display = "" if shown else "none"

    def edit_setup(self) -> None:
        """Unlock the setup; an unaccepted result is discarded."""
        if self.running:
            return
        self.results.clear()
        self._progress_box.layout.display = "none"
        self._best_values.value = ""
        self._live_note.value = ""
        self.form.set_locked(False)
        self._show_edit(False)
        self._btn_run.disabled = False
        self.status.value = "<em>Ready.</em>"
        self._include_new_measurements()
        self._refresh_warnings()

    def start_run(self) -> None:
        """Validate the setup and fit it on a background thread."""
        if self.running:
            return
        setup = self.form.get_setup()
        problems = self._setup_problems(setup)
        error = self._commit(setup)
        if error:
            problems.insert(0, error)
        prior = self._prior()
        missing = _missing(setup, prior)
        if missing:
            problems.append(f"Missing requirements: {', '.join(missing)}.")
        if missing_assumptions(setup, prior):
            problems.append("Record the values the experiment types assume first.")
        if self._species_gaps(setup):
            problems.append("Stored values lack this step's species; transfer them first.")
        if problems:
            self.status.value = status_html("error", " ".join(problems))
            return

        optimizer_name = setup.optimizer["name"]
        optimizer_kwargs = dict(setup.optimizer["knobs"])
        self._run_setup, self._run_prior = setup, prior
        self._prepare_run_info(setup)
        self.accepted = False
        self.results.clear()
        self.form.set_locked(True)
        self._show_edit(False)
        self._running = True
        self._btn_run.disabled = True
        self.status.value = status_html("running", f"Fitting {setup.name}…")
        self._refresh_checks(setup)
        self._launch(setup, prior, optimizer_name, optimizer_kwargs)

    def _prepare_run_info(self, setup: StepSetup) -> None:
        """Reset the results' best-values table and the live charts (one per measurement)."""
        try:
            variables = describe_stage(setup.stage, **setup.options)
        except ValueError:
            variables = []
        self._run_names = fitted_variables(variables, setup.frozen)
        try:
            starts = starting_values(self.study, setup, variables)
        except Exception:  # noqa: BLE001 -- units are optional in the table
            starts = {}
        self._run_units = {name: start.unit for name, start in starts.items()}
        self._best_values.value = ""
        self._reset_live(setup)

    def _finish(self, start: float) -> None:
        elapsed = time.monotonic() - start
        with self._live_write:
            self._live_token += 1
        self._running = False
        self._btn_run.disabled = False
        self._btn_cancel.layout.display = "none"
        self._progress_title.value = "<b>Convergence: best so far per objective</b>"
        result: Optional[StepResult] = self._progress.get("result")
        error = self._progress.get("error")
        if error or result is None:
            self.status.value = status_html("error", error or "The run failed.")
            self.form.set_locked(False)
        else:
            if result.cancelled:
                message = f"Cancelled after {elapsed:.0f}s; showing the last full front."
                kind = "warn"
            elif result.success:
                message, kind = f"{result.message} ({elapsed:.0f}s)", "ok"
            else:
                message, kind = result.message, "error"
            self.status.value = status_html(kind, message)
            if len(result.x):
                self.results.show(result, self._run_setup, self._run_prior)
                self._show_edit(True)
                self._btn_run.disabled = True
                self._show_final_fit()
            else:
                self.form.set_locked(False)
        self._on_study_change()
        self._notify()

    def _show_final_fit(self) -> None:
        """Show the final front's best-average candidate in the results and the live plot."""
        best = next((c for c in self.results.candidates if AVERAGE_TAG in c.tags), None)
        if best is None:
            return
        self._best_values.value = _best_values_html(
            self._run_names, self._run_units, best, self._run_setup
        )
        previews = self.results.previews_of(best)
        if previews:
            with self._live_write:
                self._show_live(previews, "Final front: best-average candidate")

    def accept(self, candidate: Optional[Candidate] = None) -> ParameterStore:
        """Write `candidate` (default: the selected one) as this step's posterior."""
        candidate = candidate or self.results.selected
        if candidate is None or self.result is None:
            raise ValueError("No candidate to accept.")
        return self._accept(candidate)

    def _accept(self, candidate: Candidate) -> ParameterStore:
        store = characterization_runner.posterior(
            self._run_setup, self.result.built, self._run_prior, candidate
        )
        self.accepted = True
        self.study.accept(self._run_setup.name, store)
        self.results.btn_accept.disabled = True
        self.results.status.value = status_html(
            "ok", f"Accepted candidate ({', '.join(candidate.tags)}) as the posterior of "
            f"{self._run_setup.name}.",
        )
        self._refresh_warnings()
        self._notify()
        return store

    def export_candidates_csv(self, path: "Path | str") -> Path:
        """Write the current run's candidates to a CSV file."""
        return self.results.export_csv(path)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
