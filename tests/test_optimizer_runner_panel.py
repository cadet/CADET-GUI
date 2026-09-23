from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Sequence

import pytest
from cadetgui.optimizer_runner import RunSpec
from cadetgui.widgets.composite._optimizer_runner_panel import OptimizerRunnerPanel
from CADETProcess.optimization import OptimizationProblem


@pytest.fixture
def _synchronous_threads(monkeypatch):
    """Same pattern as tests/test_parameter_estimation.py's fixture of the same
    name -- makes `_on_run`'s worker+ticker threads run inline and in order.

    Deliberately NOT autouse: the real-cancellation test below needs actual
    concurrent threads (a background canceller racing the run), which this
    fixture would collapse into sequential execution.
    """
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())


def _trivial_problem() -> OptimizationProblem:
    problem = OptimizationProblem("trivial")
    problem.add_variable("x", lb=-5, ub=5, transform="auto")
    problem.add_objective(lambda v: (v[0] - 2.0) ** 2)
    return problem


def _run_spec(*, accepted: dict, on_finished_calls: list) -> RunSpec:
    def render_preview(x_best: Sequence[float], ax: Any) -> None:
        ax.plot([0, 1], [x_best[0], x_best[0]])

    def render_fit_table(x_best: Mapping[str, float]) -> str:
        return f"<table><tr><td>{x_best['x']:.4g}</td></tr></table>"

    def accept(x_best: Mapping[str, float]) -> None:
        accepted.update(x_best)

    def on_finished(result: Any) -> None:
        on_finished_calls.append(result)

    return RunSpec(
        problem=_trivial_problem(), x0=[0.0],
        render_preview=render_preview, render_fit_table=render_fit_table,
        accept=accept, on_finished=on_finished,
    )


def test_run_shows_fit_table_and_accept_button_on_success(_synchronous_threads):
    accepted: dict = {}
    calls: list = []

    def build_run_spec() -> RunSpec:
        return _run_spec(accepted=accepted, on_finished_calls=calls)

    panel = OptimizerRunnerPanel(build_run_spec=build_run_spec)
    panel._knob_fields["Nelder-Mead"][0].value = 200

    panel._on_run(None)

    assert panel._last_result is not None
    assert panel._last_result.success
    assert panel._last_result.x_best["x"] == pytest.approx(2.0, abs=0.05)
    assert panel._btn_accept.layout.display == ""
    assert "table" in panel._fit_table.value
    assert len(calls) == 1 and calls[0] is panel._last_result


def test_build_run_spec_returning_a_string_aborts_with_that_error(_synchronous_threads):
    panel = OptimizerRunnerPanel(build_run_spec=lambda: "nothing to run yet")

    panel._on_run(None)

    assert "nothing to run yet" in panel.status.value
    assert panel._last_result is None
    assert panel._btn_accept.layout.display == "none"


def test_accept_calls_the_run_specs_accept_hook_with_x_best(_synchronous_threads):
    accepted: dict = {}
    calls: list = []

    def build_run_spec() -> RunSpec:
        return _run_spec(accepted=accepted, on_finished_calls=calls)

    panel = OptimizerRunnerPanel(build_run_spec=build_run_spec)
    panel._knob_fields["Nelder-Mead"][0].value = 200
    panel._on_run(None)

    panel._on_accept(None)

    assert accepted["x"] == pytest.approx(2.0, abs=0.05)
    assert panel._btn_accept.layout.display == "none"


def test_optimizer_picker_defaults_to_nelder_mead_and_switching_swaps_knob_boxes():
    panel = OptimizerRunnerPanel(build_run_spec=lambda: "unused")

    assert panel._optimizer_picker.value == "Nelder-Mead"
    assert panel._knob_boxes["Nelder-Mead"].layout.display == ""
    assert panel._knob_boxes["U-NSGA-III"].layout.display == "none"

    panel._optimizer_picker.value = "U-NSGA-III"

    assert panel._knob_boxes["Nelder-Mead"].layout.display == "none"
    assert panel._knob_boxes["U-NSGA-III"].layout.display == ""


def test_cancel_button_label_reflects_population_based_optimizers():
    panel = OptimizerRunnerPanel(build_run_spec=lambda: "unused")

    panel._optimizer_picker.value = "U-NSGA-III"
    panel._on_cancel(None)
    assert "generation" in panel._btn_cancel.description.lower()

    panel._btn_cancel.disabled = False
    panel._optimizer_picker.value = "Nelder-Mead"
    panel._on_cancel(None)
    assert "generation" not in panel._btn_cancel.description.lower()


@pytest.mark.slow
def test_cancel_stops_a_real_run_and_reports_cancelled():
    accepted: dict = {}
    calls: list = []

    def slow_problem() -> OptimizationProblem:
        # A tiny per-evaluation sleep -- otherwise this trivial 1-variable
        # quadratic converges in well under 0.3s and the cancel below never
        # actually races a still-running optimization.
        def objective(v: Sequence[float]) -> float:
            time.sleep(0.05)
            return (v[0] - 2.0) ** 2

        problem = OptimizationProblem("slow")
        problem.add_variable("x", lb=-5, ub=5, transform="auto")
        problem.add_objective(objective)
        return problem

    def build_run_spec():
        return RunSpec(
            problem=slow_problem(), x0=[0.0],
            render_preview=lambda x_best, ax: None,
            render_fit_table=lambda x_best: "",
            accept=lambda x_best: accepted.update(x_best),
            on_finished=lambda result: calls.append(result),
        )

    panel = OptimizerRunnerPanel(build_run_spec=build_run_spec)
    panel._knob_fields["Nelder-Mead"][0].value = 100_000

    def cancel_soon() -> None:
        time.sleep(0.3)
        panel._on_cancel(None)

    # `_synchronous_threads` is deliberately not requested here -- `_on_run`'s
    # own worker/ticker threads must run for real (concurrently with this
    # canceller) for cancellation mid-run to be meaningfully exercised. That
    # also means `_on_run` returns immediately, before the ticker thread has
    # necessarily called `_finish_run` -- poll for `on_finished` instead of
    # asserting right away.
    canceller = threading.Thread(target=cancel_soon)
    canceller.start()
    panel._on_run(None)
    canceller.join()
    for _ in range(200):
        if calls:
            break
        time.sleep(0.05)
    else:
        pytest.fail("run never finished")

    assert len(calls) == 1
    assert calls[0].cancelled
