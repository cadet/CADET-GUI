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

    attr: str  # constructor kwarg
    label: str  # widget field label
    default: int


@dataclass(frozen=True)
class OptimizerSpec:
    """One entry in `OPTIMIZERS`: how to build and configure an optimizer."""

    factory: Callable[..., Any]
    knobs: tuple[OptimizerKnob, ...]
    # Mirrors the optimizer class's attribute so callers need no instance; population-based
    # optimizers only reach the cancel check once per generation.
    is_population_based: bool


# `pop_size`/`n_max_gen` = 0 is falsy, which `PymooInterface` treats as "size automatically".
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
    """Raised by the hook `install_cancel_hook` installs once its event is set."""


def install_cancel_hook(optimizer: Any, cancel_event: threading.Event) -> None:
    """Make `optimizer.optimize()` raise `OptimizationCancelled` once `cancel_event` is set.

    Hooks `run_post_processing`, which every optimizer calls once per generation and
    whose exceptions propagate out of `.optimize()`. Raising from an evaluator or
    `add_callback` callback does not work (CADET-Process turns those into a bad score),
    nor does changing `maxiter` mid-run (scipy copies it at start).
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
    # Final front: independent-variable rows (`problem.independent_variable_names`) and
    # their objective rows; after a cancel, the front as of the last full generation.
    front_x: tuple[tuple[float, ...], ...] = ()
    front_f: tuple[tuple[float, ...], ...] = ()


def _front(optimizer: Any) -> tuple[tuple, tuple]:
    """Return `(front_x, front_f)` from `optimizer.results`, empty if no front exists yet."""
    results = getattr(optimizer, "results", None)
    if results is None or not results.pareto_fronts:
        return (), ()
    front = results.meta_front
    return (
        tuple(tuple(float(v) for v in row) for row in front.x_independent),
        tuple(tuple(float(v) for v in row) for row in front.f),
    )


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

    `optimizer_kwargs` go to the optimizer factory; `x0` seeds the start (one individual
    for population-based optimizers). `on_optimizer_ready` receives the optimizer just
    before the blocking `.optimize()` call, for live progress. A set `cancel_event`
    ends the run at the next generation with a cancelled result. Failures are returned
    in the result, not raised.
    """
    optimizer = OPTIMIZERS[optimizer_name].factory(**optimizer_kwargs)
    if cancel_event is not None:
        install_cancel_hook(optimizer, cancel_event)
    if on_optimizer_ready is not None:
        on_optimizer_ready(optimizer)

    try:
        results = optimizer.optimize(problem, x0=list(x0), save_results=False)
    except OptimizationCancelled:
        front_x, front_f = _front(optimizer)
        return OptimizerRunResult(
            {}, None, False, "Optimization cancelled by user.",
            cancelled=True, optimizer_name=optimizer_name, front_x=front_x, front_f=front_f,
        )
    except Exception as exc:  # noqa: BLE001
        return OptimizerRunResult({}, None, False, str(exc), optimizer_name=optimizer_name)

    # `results.x[0]` holds one value per `problem.variable_names` (dependent ones too);
    # `set_variables` takes the independent ones only.
    front_x, front_f = _front(optimizer)
    problem.set_variables(front_x[0])
    x_best = dict(zip(problem.variable_names, (float(v) for v in results.x[0])))
    return OptimizerRunResult(
        x_best, float(results.f_best[0]), True, "Optimization finished.",
        optimizer_name=optimizer_name, front_x=front_x, front_f=front_f,
    )


@dataclass(frozen=True)
class RunSpec:
    """Everything `OptimizerRunnerPanel` needs to drive one optimization run.

    `preview_series(x_best)` returns the live chart's series for a candidate point
    (positionally parallel to `problem.variable_names`), or `None` when the signal is
    not a time x component trace; it must not touch state the worker thread writes.
    `render_preview(x_best, ax)` is the matplotlib fallback drawing onto the panel's
    `Axes`. `render_fit_table` maps `{variable_name: value}` to an HTML table. `accept`
    receives the same mapping when the user accepts the fit and writes it back.
    `on_finished` is called once when a run ends (finished, failed or cancelled).
    """

    problem: OptimizationProblem
    x0: list[float]
    render_preview: Callable[[Sequence[float], Any], None]
    render_fit_table: Callable[[Mapping[str, float]], str]
    accept: Callable[[Mapping[str, float]], None]
    on_finished: Optional[Callable[[OptimizerRunResult], None]] = None
    preview_series: Optional[Callable[[Sequence[float]], Optional[list[dict[str, Any]]]]] = None
