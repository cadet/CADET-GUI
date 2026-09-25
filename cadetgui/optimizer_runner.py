from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from CADETProcess.optimization import U_NSGA3, NelderMead, OptimizationProblem

__all__ = [
    "OptimizerKnob",
    "OptimizerSpec",
    "OPTIMIZERS",
    "OptimizationCancelled",
    "install_cancel_hook",
    "OptimizerRunResult",
    "run_optimization",
    "RunSpec",
]


@dataclass(frozen=True)
class OptimizerKnob:
    """One optimizer-specific numeric setting, e.g. Nelder-Mead's `maxiter`."""

    attr: str  # kwarg name passed to the optimizer's constructor
    label: str  # widget field label
    default: int


@dataclass(frozen=True)
class OptimizerSpec:
    """One entry in `OPTIMIZERS` -- everything needed to build and configure it."""

    factory: Callable[..., Any]
    knobs: tuple[OptimizerKnob, ...]
    # Mirrors the optimizer class's own `is_population_based` (`OptimizerBase`
    # attribute) -- surfaced separately so callers don't need to construct an
    # instance just to read it (e.g. for a "this may take a while to cancel"
    # UX note: population-based optimizers evaluate a whole population before
    # the per-generation cancellation check is next reached, see
    # `install_cancel_hook`).
    is_population_based: bool


# Adding another optimizer later is one more entry here -- nothing else in
# this module, in `cadetgui.parameter_estimation`, or in a widget hardcodes
# "Nelder-Mead"/"U-NSGA-III"; every caller reads `OPTIMIZERS` generically.
# `pop_size`/`n_max_gen` default to `0`, which is falsy -- `PymooInterface`
# (CADETProcess/optimization/pymooAdapter.py) already treats an unset/falsy
# value as "size this automatically" via its own `scale_problem_size`
# heuristic, so `0` here means "let CADET-Process decide," not "population
# of zero."
OPTIMIZERS: dict[str, OptimizerSpec] = {
    "Nelder-Mead": OptimizerSpec(
        factory=NelderMead,
        knobs=(OptimizerKnob("maxiter", "Max iterations", 1000),),
        is_population_based=False,
    ),
    "U-NSGA-III": OptimizerSpec(
        factory=U_NSGA3,
        knobs=(
            OptimizerKnob("pop_size", "Population size", 0),
            OptimizerKnob("n_max_gen", "Max generations", 0),
        ),
        is_population_based=True,
    ),
}


class OptimizationCancelled(Exception):
    """Raised by the per-generation hook `install_cancel_hook` installs.

    Triggered once a caller sets the `cancel_event` passed to
    `run_optimization`, mid-run.
    """


def install_cancel_hook(optimizer: Any, cancel_event: threading.Event) -> None:
    """Make `optimizer.optimize()` raise `OptimizationCancelled` once `cancel_event` is set.

    `OptimizerBase.run_post_processing` (defined once, shared by every
    adapter) is called once per generation for every optimizer -- from
    inside scipy's own callback for `SciPyInterface` subclasses (`NelderMead`,
    ...), and from inside CADET-Process's own generation loop for
    `PymooInterface` subclasses (`U_NSGA3`, ...) -- and nothing wraps the call
    to `_run` in a try/except, so an exception raised from here propagates
    all the way out of `.optimize()` regardless of which optimizer is
    running. Raising from an evaluator or an `OptimizationProblem.add_callback()`
    callback does *not* work: CADET-Process's evaluation pipeline deliberately
    catches exceptions from both and converts them into a bad-score fallback,
    by design, so a single flaky simulation doesn't kill an entire
    optimization. Mutating `optimizer.maxiter` after `.optimize()` has started
    doesn't work either -- `SciPyInterface._run` reads it once into a plain
    dict scipy owns from then on, not a live reference.
    """
    original = optimizer.run_post_processing

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        if cancel_event.is_set():
            raise OptimizationCancelled("Optimization cancelled by user.")
        return original(*args, **kwargs)

    optimizer.run_post_processing = _wrapped


@dataclass(frozen=True)
class OptimizerRunResult:
    """Outcome of `run_optimization` -- generic over any `OptimizationProblem`."""

    x_best: dict[str, float]  # keyed by `problem.variable_names`
    objective: Optional[float]
    success: bool
    message: str
    cancelled: bool = False
    optimizer_name: str = ""


def run_optimization(
    problem: OptimizationProblem,
    optimizer_name: str,
    optimizer_kwargs: Mapping[str, int],
    x0: Sequence[float],
    *,
    cancel_event: Optional[threading.Event] = None,
    on_optimizer_ready: Optional[Callable[[Any], None]] = None,
) -> OptimizerRunResult:
    """Run `OPTIMIZERS[optimizer_name]` against an already-built `problem`.

    Fully generic over what built `problem` -- a hand-rolled single-reference
    `OptimizationProblem` (`cadetgui.parameter_estimation.build_estimation_problem`)
    and a `CADETProcess.characterization.CharacterizeXxx` instance (itself an
    `OptimizationProblem` subclass) both work here unchanged, since neither
    this function nor `OptimizerBase.optimize()` cares how `problem` was
    constructed.

    `optimizer_kwargs` are passed straight to `OPTIMIZERS[optimizer_name]
    .factory(**optimizer_kwargs)` (e.g. `{"maxiter": 1000}` for Nelder-Mead).
    `x0` seeds the optimizer's starting point -- for a population-based
    optimizer like U-NSGA-III it seeds one individual of the initial
    population, the rest filled in by CADET-Process's own polytope sampling.

    `on_optimizer_ready`, when given, is called exactly once with the
    constructed optimizer instance, right before the blocking `.optimize()`
    call -- the hook a caller running this on a background thread needs to
    obtain a live handle to `optimizer.results` for progress reporting.

    `cancel_event`, when given, is checked once per generation (via
    `install_cancel_hook`) -- the run stops there and returns a cancelled
    result instead of a normal one.
    """
    optimizer = OPTIMIZERS[optimizer_name].factory(**optimizer_kwargs)
    if cancel_event is not None:
        install_cancel_hook(optimizer, cancel_event)
    if on_optimizer_ready is not None:
        on_optimizer_ready(optimizer)

    try:
        results = optimizer.optimize(problem, x0=list(x0), save_results=False)
    except OptimizationCancelled:
        return OptimizerRunResult(
            {}, None, False, "Optimization cancelled by user.",
            cancelled=True, optimizer_name=optimizer_name,
        )
    except Exception as exc:  # noqa: BLE001
        return OptimizerRunResult({}, None, False, str(exc), optimizer_name=optimizer_name)

    # `results.x[0]` is the full, dependency-resolved point (one entry per
    # `problem.variable_names`, in that order -- confirmed live: a dependent
    # variable's resolved value is included, not just the independent ones a
    # mid-run objective evaluation receives). `set_variables` accepts exactly
    # that shape for a problem with no dependent variables (every current
    # caller: cadetgui's own hand-built estimation problems, and every
    # CADETProcess.characterization.CharacterizeXxx stage this module
    # supports never uses `add_variable_dependency`); a problem that does
    # isn't supported here.
    problem.set_variables(results.x[0])
    x_best = dict(zip(problem.variable_names, (float(v) for v in results.x[0])))
    return OptimizerRunResult(
        x_best, float(results.f_best[0]), True, "Optimization finished.",
        optimizer_name=optimizer_name,
    )


@dataclass(frozen=True)
class RunSpec:
    """Everything needed to drive one optimization run.

    Built by `OptimizerRunnerPanel` (widgets/composite/_optimizer_runner_panel.py)'s
    caller, supplied fresh on every "Run" click via a `build_run_spec` callback.

    `preview_series(x_best)`, when given, is called during the live-progress
    ticker with a candidate point's values (positionally parallel to
    `problem.variable_names`) and returns the interactive live chart's series
    (one per component, plus the measured reference), or `None` when the
    candidate's signal isn't a time x component trace. It must never mutate
    anything the worker thread is writing to (simulate a fresh deep copy).

    `render_preview(x_best, ax)` is the matplotlib fallback used whenever
    `preview_series` is absent or returns `None`: it must draw onto the given
    (already-created) `Axes`. The panel itself owns the figure this `Axes`
    belongs to (it's laid out next to a generic objective-history panel the
    panel draws on its own).

    `render_fit_table` turns a `{variable_name: fitted_value}` mapping into
    an HTML results table. `accept` is called once, with the same mapping,
    when the user clicks "Accept" -- it decides where each fitted value gets
    written back (a `ConfigurationWidget`'s column/binding form, an
    `InstrumentWidget` unit's form, ...); this module has no opinion on that.

    `on_finished`, when given, is called once after a run ends (successful,
    failed, or cancelled) with the raw `OptimizerRunResult` -- the hook a
    caller with its own post-fit display beyond the fit table/live-progress
    panel (e.g. `ParameterEstimationWidget`'s reference-vs-simulated overlay)
    uses to refresh it.
    """

    problem: OptimizationProblem
    x0: list[float]
    render_preview: Callable[[Sequence[float], Any], None]
    render_fit_table: Callable[[Mapping[str, float]], str]
    accept: Callable[[Mapping[str, float]], None]
    on_finished: Optional[Callable[[OptimizerRunResult], None]] = None
    preview_series: Optional[Callable[[Sequence[float]], Optional[list[dict[str, Any]]]]] = None
