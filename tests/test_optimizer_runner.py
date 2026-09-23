from __future__ import annotations

import threading
import time

import pytest
from cadetgui.optimizer_runner import OPTIMIZERS, run_optimization
from CADETProcess.optimization import NelderMead, OptimizationProblem


def _trivial_problem() -> OptimizationProblem:
    """A fast, pure-Python 2-variable quadratic -- no CADET simulation involved."""
    problem = OptimizationProblem("trivial")
    problem.add_variable("x", lb=-5, ub=5, transform="auto")
    problem.add_variable("y", lb=-5, ub=5, transform="auto")
    problem.add_objective(lambda v: (v[0] - 2.0) ** 2 + (v[1] + 1.0) ** 2)
    return problem


def test_run_optimization_converges_and_reports_named_x_best():
    result = run_optimization(
        _trivial_problem(), "Nelder-Mead", {"maxiter": 200}, x0=[0.0, 0.0]
    )

    assert result.success
    assert not result.cancelled
    assert set(result.x_best) == {"x", "y"}
    assert result.x_best["x"] == pytest.approx(2.0, abs=0.05)
    assert result.x_best["y"] == pytest.approx(-1.0, abs=0.05)
    assert result.objective < 1e-2


def test_run_optimization_reports_the_error_instead_of_raising():
    problem = OptimizationProblem("broken")
    problem.add_variable("x", lb=-5, ub=5)

    def broken_objective(v):
        raise RuntimeError("synthetic objective failure")

    problem.add_objective(broken_objective)

    result = run_optimization(problem, "Nelder-Mead", {"maxiter": 5}, x0=[0.0])

    assert not result.success
    assert not result.cancelled
    assert result.x_best == {}


def test_optimizers_registry_has_both_entries_with_expected_knobs():
    assert set(OPTIMIZERS) == {"Nelder-Mead", "U-NSGA-III"}
    assert OPTIMIZERS["Nelder-Mead"].factory is NelderMead
    assert not OPTIMIZERS["Nelder-Mead"].is_population_based
    assert OPTIMIZERS["U-NSGA-III"].is_population_based


@pytest.mark.slow
def test_run_optimization_stops_promptly_once_cancelled():
    cancel_event = threading.Event()

    def cancel_soon() -> None:
        time.sleep(0.3)
        cancel_event.set()

    # A tiny per-evaluation sleep -- otherwise this trivial 2-variable
    # quadratic converges in well under 0.3s and the cancel below never
    # actually races a still-running optimization.
    def slow_problem() -> OptimizationProblem:
        def objective(v):
            time.sleep(0.05)
            return (v[0] - 2.0) ** 2 + (v[1] + 1.0) ** 2

        problem = OptimizationProblem("slow_trivial")
        problem.add_variable("x", lb=-5, ub=5, transform="auto")
        problem.add_variable("y", lb=-5, ub=5, transform="auto")
        problem.add_objective(objective)
        return problem

    threading.Thread(target=cancel_soon, daemon=True).start()

    start = time.monotonic()
    result = run_optimization(
        slow_problem(), "Nelder-Mead", {"maxiter": 100_000}, x0=[0.0, 0.0],
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - start

    assert result.cancelled
    assert not result.success
    assert elapsed < 5.0
