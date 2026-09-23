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
from CADETProcess.optimization import OptimizationProblem
from CADETProcess.processModel import ComponentSystem
from CADETProcess.reference import ReferenceIO
from CADETProcess.simulator import Cadet

from .cadetprocessadapter import FieldSpec
from .optimizer_runner import OPTIMIZERS, OptimizerKnob, OptimizerSpec, run_optimization
from .simulation import run_process

# OptimizerKnob/OptimizerSpec/OPTIMIZERS live in `cadetgui.optimizer_runner` now
# (shared with any caller driving a `CADETProcess.characterization.CharacterizeXxx`
# problem, not just this module's own `run_estimation`) -- re-exported here so
# existing imports of `cadetgui.parameter_estimation.OPTIMIZERS` keep working.
__all__ = [
    "FittableParameter",
    "EstimationResult",
    "OptimizerKnob",
    "OptimizerSpec",
    "OPTIMIZERS",
    "list_fittable_parameters",
    "build_reference",
    "calibrate_reference",
    "build_estimation_problem",
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
            transform="auto",
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


def build_estimation_problem(
    process: Any,
    column: Any,
    params: Sequence[FittableParameter],
    selected_indices: Sequence[int],
    reference: ReferenceIO,
    solution_path: str,
    *,
    component_name: Optional[str] = None,
) -> tuple[OptimizationProblem, Any]:
    """Build the `OptimizationProblem` `run_estimation` fits, without running it.

    Never touches `process` -- everything is built around a deep copy.
    Returns `(problem, working_process)`: `working_process` is that same deep
    copy, needed by `run_estimation` afterwards to populate
    `EstimationResult.fitted_process` (fitted values are only meant to reach
    the real configuration through an explicit, user-approved write-back,
    PRODUCT_VISION.md §16.4 -- never silently overwrite the source model).

    `component_name`, when given, restricts the comparison to that one
    simulated component (`SSE(..., components=[component_name])`) -- the right
    choice whenever the measured signal is specific to one molecule, which is
    the common case. Left `None`, every simulated component is summed first
    (`use_total_concentration=True`) before differencing, appropriate only for
    a genuinely blended/overlapping signal (e.g. a non-selective detector).
    """
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

    simulator = Cadet()
    problem.add_evaluator(simulator)
    problem.add_objective(comparator, n_objectives=comparator.n_metrics, requires=[simulator])

    return problem, working_process


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

    A thin wrapper: `build_estimation_problem` builds the problem, then
    `cadetgui.optimizer_runner.run_optimization` runs it -- see both
    docstrings for `optimizer_name`/`starts`/`on_optimizer_ready`/
    `cancel_event` semantics, which this function passes straight through
    unchanged.
    """
    if not selected_indices:
        return EstimationResult({}, None, False, "No parameters selected to fit.")

    problem, working_process = build_estimation_problem(
        process, column, params, selected_indices, reference, solution_path,
        component_name=component_name,
    )
    result = run_optimization(
        problem, optimizer_name, optimizer_kwargs, list(starts),
        cancel_event=cancel_event, on_optimizer_ready=on_optimizer_ready,
    )
    if result.cancelled:
        return EstimationResult({}, None, False, result.message, cancelled=True)
    if not result.success:
        return EstimationResult({}, None, False, result.message)

    fitted = {idx: result.x_best[f"var_{idx}"] for idx in selected_indices}
    return EstimationResult(fitted, result.objective, True, result.message, working_process)
