from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Sequence

import numpy as np
import numpy.typing as npt
from CADETProcess.calibration import apply_beer_lambert, normalize_area
from CADETProcess.comparison import Comparator
from CADETProcess.comparison.difference import SSE
from CADETProcess.optimization import U_NSGA3, NelderMead, OptimizationProblem
from CADETProcess.processModel import ComponentSystem
from CADETProcess.reference import ReferenceIO
from CADETProcess.simulator import Cadet

from .cadetprocessadapter import FieldSpec
from .simulation import run_process

__all__ = [
    "FittableParameter",
    "EstimationResult",
    "OptimizerKnob",
    "OptimizerSpec",
    "OPTIMIZERS",
    "list_fittable_parameters",
    "build_reference",
    "calibrate_reference",
    "run_estimation",
    "simulate_at",
]

CalibrationMethod = Literal["none", "beer_lambert", "normalize_area"]

_FITTABLE_KINDS = ("float", "float_list")


@dataclass(frozen=True)
class FittableParameter:
    """One column/binding attribute (or one component of a per-component one) to fit."""

    owner: Literal["column", "binding"]
    name: str
    label: str
    component_index: Optional[int]
    current_value: float
    lb: float
    ub: float


def _bounds(field: FieldSpec, current: float) -> tuple[float, float]:
    lb = field.min if field.min is not None else 0.0
    ub = field.max if field.max is not None else (10.0 * current if current else 1.0)
    return lb, ub


def list_fittable_parameters(
    owner: Literal["column", "binding"],
    fields: Sequence[FieldSpec],
    values: Mapping[str, Any],
) -> list[FittableParameter]:
    """List the fittable (float/float_list) fields, one entry per scalar/component.

    Non-numeric kinds ("bool", "text", "choice" -- e.g. `is_kinetic`) aren't
    fittable and are skipped.
    """
    params: list[FittableParameter] = []
    for field in fields:
        if field.kind not in _FITTABLE_KINDS:
            continue
        if field.kind == "float":
            current = float(values[field.name])
            lb, ub = _bounds(field, current)
            label = field.label or field.name
            params.append(FittableParameter(owner, field.name, label, None, current, lb, ub))
            continue

        for i, current in enumerate(values[field.name]):
            current = float(current)
            lb, ub = _bounds(field, current)
            component = field.component_names[i] if field.component_names else str(i)
            label = f"{field.label or field.name} — {component}"
            params.append(FittableParameter(owner, field.name, label, i, current, lb, ub))
    return params


def build_reference(
    label: str,
    time_min: npt.ArrayLike,
    signal: npt.ArrayLike,
    *,
    component_name: Optional[str] = None,
) -> ReferenceIO:
    """Wrap an imported (time_min, signal) pair as a CADET-Process reference.

    Time is converted to seconds to match the simulation's own time grid.
    `component_name`, when given, tags the reference as representing exactly
    that one simulated component (see `run_estimation`'s `component_name`) --
    required for a single-channel detector signal that's only sensitive to one
    molecule, the common case. Left `None`, the reference is unnamed and
    `run_estimation` falls back to comparing against the summed total
    concentration of every component (a blended/overlapping signal).
    """
    component_system = ComponentSystem([component_name]) if component_name else None
    return ReferenceIO(
        label, np.asarray(time_min) * 60.0, np.asarray(signal), component_system=component_system
    )


def calibrate_reference(
    reference: ReferenceIO, method: CalibrationMethod, **kwargs: float
) -> ReferenceIO:
    """Convert a raw imported signal (e.g. UV mAU) to concentration-equivalent units.

    Thin wrapper over `CADETProcess.calibration` -- the actual conversions
    (`apply_beer_lambert`, `normalize_area`) are native, not reimplemented here.
    "none" (the default) returns `reference` unchanged, matching the previous
    behavior of comparing the raw signal directly.
    """
    if method == "none":
        return reference
    if method == "beer_lambert":
        calibrated = apply_beer_lambert(
            reference, kwargs["extinction_coefficient"], kwargs["path_length"]
        )
    elif method == "normalize_area":
        calibrated = normalize_area(reference, kwargs["target_area"])
    else:
        raise ValueError(f"Unknown calibration method: {method!r}")

    # Neither native helper carries the input's component_system over onto the
    # new ReferenceIO it builds -- reattach it, or a `component_name` passed to
    # `build_reference` silently stops being respected by `run_estimation`.
    return ReferenceIO(
        calibrated.name, calibrated.time, calibrated.solution, calibrated.flow_rate,
        component_system=reference.component_system,
    )


def _unit_name(process: Any, unit: Any) -> str:
    return next(name for name, u in process.flow_sheet.units_dict.items() if u is unit)


def _parameter_path(process: Any, column: Any, param: FittableParameter) -> str:
    unit_name = _unit_name(process, column)
    if param.owner == "column":
        return f"flow_sheet.{unit_name}.{param.name}"
    return f"flow_sheet.{unit_name}.binding_model.{param.name}"


def _register_variables(
    problem: OptimizationProblem,
    working_process: Any,
    working_column: Any,
    params: Sequence[FittableParameter],
    selected_indices: Sequence[int],
) -> None:
    """Register one `add_variable` per selected parameter, in order.

    Shared between `run_estimation`'s real optimization problem and
    `simulate_at`'s throwaway one -- both need the exact same variables
    registered the exact same way for `problem.set_variables(values)` to
    write `values` onto the right attributes.
    """
    for idx in selected_indices:
        param = params[idx]
        kwargs: dict[str, Any] = {}
        if param.component_index is not None:
            kwargs["indices"] = (param.component_index,)
        problem.add_variable(
            name=f"var_{idx}",
            parameter_path=_parameter_path(working_process, working_column, param),
            lb=param.lb,
            ub=param.ub,
            # "auto" lets CADET-Process pick a sensible per-variable scaling
            # (e.g. log for a wide-dynamic-range rate constant, linear
            # otherwise) -- without it every variable is optimized in its own
            # raw, wildly different units (e.g. porosity ~0.7 next to axial
            # dispersion ~1e-8), which Nelder-Mead's simplex handles poorly.
            normalization="auto",
            **kwargs,
        )


def simulate_at(
    process: Any,
    column: Any,
    params: Sequence[FittableParameter],
    selected_indices: Sequence[int],
    values: Sequence[float],
) -> Any:
    """Simulate `process` with `values` written onto the selected parameters.

    Deep-copies `process` first -- never touches the caller's own object, and
    in particular never touches any other deep copy an optimization run might
    be actively mutating elsewhere (e.g. `run_estimation`'s own
    `working_process`, which a background optimization thread writes to on
    every objective evaluation -- reading or writing it concurrently from
    here would be a real race). Meant for periodic "what does the process
    look like at this candidate point" previews, e.g. a live progress plot,
    fully decoupled from whatever optimization run produced `values`.
    """
    working_process = copy.deepcopy(process)
    working_column = working_process.flow_sheet.units_dict[_unit_name(process, column)]

    problem = OptimizationProblem("simulate_at")
    problem.add_evaluation_object(working_process)
    _register_variables(problem, working_process, working_column, params, selected_indices)
    problem.set_variables(list(values))

    return run_process(working_process)


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
    # `_install_cancel_hook`).
    is_population_based: bool


# Adding another optimizer later is one more entry here -- nothing else in
# this module or in the widget hardcodes "Nelder-Mead"/"U-NSGA-III"; both
# read `OPTIMIZERS` generically. `pop_size`/`n_max_gen` default to `0`,
# which is falsy -- `PymooInterface` (CADETProcess/optimization/
# pymooAdapter.py) already treats an unset/falsy value as "size this
# automatically" via its own `scale_problem_size` heuristic, so `0` here
# means "let CADET-Process decide," not "population of zero."
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


class EstimationCancelled(Exception):
    """Raised by the per-generation hook `_install_cancel_hook` installs.

    Triggered once a caller sets the `cancel_event` passed to
    `run_estimation`, mid-run.
    """


def _install_cancel_hook(optimizer: Any, cancel_event: threading.Event) -> None:
    """Make `optimizer.optimize()` raise `EstimationCancelled` once `cancel_event` is set.

    Verified (live test, not assumed) that this is the only reliable stop
    point: raising from inside an evaluator or a `CADETProcess.optimization.
    OptimizationProblem.add_callback()` callback does *not* abort the run --
    CADET-Process's evaluation pipeline deliberately catches exceptions from
    both and converts them into a bad-score fallback (`EvaluationFailure`),
    by design, so a single flaky simulation doesn't kill an entire
    optimization. Mutating `optimizer.maxiter` after `.optimize()` has
    started doesn't work either -- `SciPyInterface._run` reads it once into
    a plain dict scipy owns from then on, not a live reference.

    What *does* work, for *every* optimizer, not just scipy-based ones:
    `OptimizerBase.run_post_processing` (defined once, shared by every
    adapter) is called directly, as plain Python, once per generation --
    from inside scipy's own callback for `SciPyInterface` subclasses
    (`NelderMead`, ...), and from inside CADET-Process's own hand-rolled
    generation loop for `PymooInterface` subclasses (`U_NSGA3`, ...).
    Confirmed by reading `OptimizerBase.optimize()`: nothing wraps the call
    to `_run` in a try/except (a `log.log_exceptions(...)`-wrapped version
    is constructed but its result is discarded -- dead code), so an
    exception raised here propagates all the way out of `.optimize()`
    regardless of which optimizer subclass is running. Verified live for
    both `NelderMead` and `U_NSGA3`: this exact mechanism aborted a real
    `.optimize()` call for each. Solver-agnostic by construction -- a future
    optimizer added to `OPTIMIZERS` gets working cancellation for free as
    long as it's an ordinary `OptimizerBase` subclass (true for every
    built-in CADET-Process optimizer; `run_post_processing` isn't something
    each adapter reimplements).

    (This replaces an earlier version that instance-patched the
    `SciPyInterface`-only `get_callback()` method -- worked for NelderMead,
    but `PymooInterface` has no such method at all, and it also required
    matching scipy's own callback-signature-inspection exactly, a fragility
    this simpler hook doesn't have.)
    """
    original = optimizer.run_post_processing

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        if cancel_event.is_set():
            raise EstimationCancelled("Estimation cancelled by user.")
        return original(*args, **kwargs)

    optimizer.run_post_processing = _wrapped


@dataclass(frozen=True)
class EstimationResult:
    """Outcome of `run_estimation`."""

    fitted: dict[int, float]
    objective: Optional[float]
    success: bool
    message: str
    # The detached, fitted copy of `process` -- safe to simulate/plot from, but
    # never the caller's own process (see `run_estimation`'s docstring).
    fitted_process: Optional[Any] = None
    cancelled: bool = False


def run_estimation(
    process: Any,
    column: Any,
    params: Sequence[FittableParameter],
    selected_indices: Sequence[int],
    reference: ReferenceIO,
    solution_path: str,
    *,
    optimizer_name: str,
    optimizer_kwargs: Mapping[str, int],
    starts: Sequence[float],
    component_name: Optional[str] = None,
    on_optimizer_ready: Optional[Callable[[Any], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> EstimationResult:
    """Fit the selected parameters against `reference`, never touching `process`.

    Runs on a deep copy of `process` -- fitted values are only meant to reach
    the real configuration through an explicit, user-approved write-back
    (PRODUCT_VISION.md §16.4: never silently overwrite the source model).

    `optimizer_name` selects an entry from `OPTIMIZERS`; `optimizer_kwargs`
    are passed straight to that entry's `factory(**optimizer_kwargs)` (e.g.
    `{"maxiter": 1000}` for Nelder-Mead, `{"pop_size": 200, "n_max_gen": 50}`
    for U-NSGA-III) -- this function itself is fully optimizer-agnostic
    beyond this one construction step; `OptimizationProblem`/variable
    registration/the `optimize()` call are identical regardless of which
    optimizer runs (confirmed: `OptimizerBase.optimize()` is never
    overridden by any concrete optimizer).

    `starts` gives the optimizer's initial guess, positionally parallel to
    `selected_indices` -- deliberately not implied by `params[i].current_value`,
    since a starting guess is a property of the estimation run, not of the
    live configuration (confirmed: `OptimizationProblem.add_variable()` has no
    per-variable starting-value concept, only `optimize()`'s `x0`). For a
    population-based optimizer like U-NSGA-III, `x0` seeds one individual of
    the initial population rather than a single starting point -- the rest is
    filled in by CADET-Process's own `create_initial_values` polytope
    sampling (confirmed by reading `PymooInterface._run`), so no special
    handling is needed here for that case either.

    `component_name`, when given, restricts the comparison to that one
    simulated component (`SSE(..., components=[component_name])`) -- the right
    choice whenever the measured signal is specific to one molecule, which is
    the common case. Left `None`, every simulated component is summed first
    (`use_total_concentration=True`) before differencing, appropriate only for
    a genuinely blended/overlapping signal (e.g. a non-selective detector) --
    anything more specific (per-wavelength deconvolution) is out of scope here.

    `on_optimizer_ready`, when given, is called exactly once with the
    constructed `NelderMead` instance, right before the blocking `.optimize()`
    call. This is the hook a caller running this on a background thread needs
    to obtain a live handle to `optimizer.results` (populated incrementally,
    one generation at a time, regardless of `save_results`) and poll it from
    elsewhere for progress reporting -- see `simulate_at` for how to safely
    preview a candidate point without touching this run's own working copy.

    `cancel_event`, when given, is checked once per generation (right after
    it finishes, via `_install_cancel_hook` -- see there for exactly why
    this is the only point that actually works) -- the run stops there and
    returns a cancelled result (`EstimationResult.cancelled=True`) instead
    of a normal one.
    """
    if not selected_indices:
        return EstimationResult({}, None, False, "No parameters selected to fit.")

    working_process = copy.deepcopy(process)
    working_column = working_process.flow_sheet.units_dict[_unit_name(process, column)]

    if component_name is not None:
        metric = SSE(reference, components=[component_name])
    else:
        metric = SSE(reference, use_total_concentration=True)
    comparator = Comparator()
    comparator.add_difference_metric(metric, solution_path)

    problem = OptimizationProblem("parameter_estimation")
    problem.add_evaluation_object(working_process)
    _register_variables(problem, working_process, working_column, params, selected_indices)
    x0 = list(starts)

    simulator = Cadet()
    problem.add_evaluator(simulator)
    problem.add_objective(comparator, n_objectives=comparator.n_metrics, requires=[simulator])

    optimizer = OPTIMIZERS[optimizer_name].factory(**optimizer_kwargs)
    if cancel_event is not None:
        _install_cancel_hook(optimizer, cancel_event)
    if on_optimizer_ready is not None:
        on_optimizer_ready(optimizer)

    try:
        results = optimizer.optimize(problem, x0=x0, save_results=False)
    except EstimationCancelled:
        return EstimationResult({}, None, False, "Estimation cancelled by user.", cancelled=True)
    except Exception as exc:  # noqa: BLE001
        return EstimationResult({}, None, False, str(exc))

    problem.set_variables(results.x[0])  # write the best point onto working_process
    fitted = dict(zip(selected_indices, (float(v) for v in results.x[0])))
    return EstimationResult(
        fitted, float(results.f_best[0]), True, "Estimation finished.", working_process
    )
