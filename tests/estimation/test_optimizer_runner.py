"""Running an optimizer on a trivial problem: result, failure, progress, cancel, front."""
from __future__ import annotations

import threading

import pytest
from cadetgui.estimation.optimizer_runner import run_optimization
from CADETProcess.optimization import OptimizationProblem


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [("Nelder-Mead", {"maxiter": 200}), ("U-NSGA-III", {"pop_size": 8, "n_max_gen": 3})],
)
def test_run_reports_named_x_best_front_and_the_optimizer(trivial_problem, name, kwargs):
    seen = []

    result = run_optimization(
        trivial_problem(), name, kwargs, x0=[0.0, 0.0], on_optimizer_ready=seen.append
    )

    assert result.success and not result.cancelled
    assert set(result.x_best) == {"x", "y"}
    assert result.optimizer_name == name
    assert len(seen) == 1
    assert result.front_x and len(result.front_x[0]) == 2
    if name == "Nelder-Mead":
        assert result.x_best["x"] == pytest.approx(2.0, abs=0.05)
        assert result.x_best["y"] == pytest.approx(-1.0, abs=0.05)
        assert result.objective < 1e-2


def test_a_failing_objective_is_reported_not_raised():
    problem = OptimizationProblem("broken")
    problem.add_variable("x", lb=-5, ub=5)

    def broken(v):
        raise RuntimeError("synthetic failure")

    problem.add_objective(broken)

    result = run_optimization(problem, "Nelder-Mead", {"maxiter": 5}, x0=[0.0])

    assert not result.success and not result.cancelled
    assert result.x_best == {} and result.message


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [("Nelder-Mead", {"maxiter": 100_000}), ("U-NSGA-III", {"pop_size": 4, "n_max_gen": 1000})],
)
def test_cancel_stops_the_run_and_keeps_the_front_so_far(name, kwargs):
    cancel = threading.Event()
    evaluations = []

    def objective(v):
        evaluations.append(v)
        if len(evaluations) == 6:
            cancel.set()
        return (v[0] - 2.0) ** 2 + (v[1] + 1.0) ** 2

    problem = OptimizationProblem("cancelled")
    for variable in ("x", "y"):
        problem.add_variable(variable, lb=-5, ub=5, transform="auto")
    problem.add_objective(objective)

    result = run_optimization(problem, name, kwargs, x0=[0.0, 0.0], cancel_event=cancel)

    assert result.cancelled and not result.success
    assert len(evaluations) < 100
    if name == "U-NSGA-III":
        assert result.front_x
