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

from .cadetprocessadapter import FieldSpec
from .optimizer_runner import run_optimization
from .simulation import Simulator, run_process

__all__ = [
    "FittableParameter",
    "EstimationResult",
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
    """List the numeric fields as fittable parameters, one per scalar or component."""
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
    """Wrap an imported (time in minutes, signal) pair as a reference in seconds.

    `component_name` tags a signal specific to one component; without it the fit
    compares against the summed concentration of all components.
    """
    component_system = ComponentSystem([component_name]) if component_name else None
    return ReferenceIO(
        label, np.asarray(time_min) * 60.0, np.asarray(signal), component_system=component_system
    )


def calibrate_reference(
    reference: ReferenceIO, method: CalibrationMethod, **kwargs: float
) -> ReferenceIO:
    """Convert a raw signal (e.g. UV mAU) to concentration-equivalent units; "none" is a no-op."""
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

    # The CADET-Process helpers drop the component system; reattach it.
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
    """Register one variable per selected parameter, in order, named `var_<index>`."""
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
            # Raw units span orders of magnitude (porosity ~0.7, dispersion ~1e-8).
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
    """Simulate a deep copy of `process` with `values` written onto the selected parameters.

    Safe to call from a preview while an optimization thread mutates its own copy.
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
    # Detached copy of `process` with the fitted values; never the caller's own.
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
    """Build the `OptimizationProblem` for fitting `reference`, without running it.

    Returns `(problem, working_process)`, where `working_process` is the deep copy the
    problem mutates; `process` itself is never touched. `component_name` restricts the
    comparison to one simulated component, otherwise all components are summed first.
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

    simulator = Simulator()
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
    """Fit the selected parameters against `reference` without touching `process`.

    Chains `build_estimation_problem` and `run_optimization`, which define the
    optimizer arguments.
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
