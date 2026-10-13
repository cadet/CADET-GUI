"""OptimizerRunnerPanel on a trivial problem: run, accept, cancel, progress, analytics."""
from __future__ import annotations

import dataclasses
import threading
import time

import pytest
from cadetgui.estimation.optimizer_runner import RunSpec
from cadetgui.widgets.estimation import OptimizerRunnerPanel


@pytest.fixture
def run_spec(trivial_problem):
    """A RunSpec over the one-variable quadratic that records accept and on_finished."""
    def make(delay: float = 0.0, **overrides) -> RunSpec:
        spec = RunSpec(
            problem=trivial_problem(n_var=1, delay=delay), x0=[0.0],
            render_preview=lambda x_best, ax: ax.plot([0, 1], [x_best[0]] * 2),
            render_fit_table=lambda x_best: f"<table><td>{x_best['x']:.4g}</td></table>",
            accept=lambda x_best: make.accepted.update(x_best),
            on_finished=make.finished.append,
        )
        return dataclasses.replace(spec, **overrides)

    make.accepted, make.finished = {}, []
    return make


@pytest.fixture
def panel(run_spec):
    panel = OptimizerRunnerPanel(build_run_spec=run_spec)
    panel._knob_fields["Nelder-Mead"][0].value = 200
    return panel


class FakeResults:
    """Optimizer results with `n_gen` generations of `n_var` variables."""

    def __init__(self, n_gen=2, n_var=1, fail=False):
        self.populations = [None] * n_gen
        self.f_best_history = [[1.0]] * n_gen
        self.x = [[0.5] * n_var]
        self.fail = fail

    def plot_convergence(self, ax):
        if self.fail:
            raise RuntimeError("synthetic analytics failure")
        ax[0].plot([1, 2, 3])

    def plot_pairwise(self, ax):
        pass


def optimizer(**kwargs):
    return type("FakeOptimizer", (), {"results": FakeResults(**kwargs)})()


def test_run_shows_the_fit_and_accept_writes_it_back(panel, run_spec, synchronous_threads):
    panel._on_run(None)

    (result,) = run_spec.finished
    assert result.success and result.x_best["x"] == pytest.approx(2.0, abs=0.05)
    assert "table" in panel._fit_table.value
    assert not panel.running

    panel._btn_accept.click()

    assert run_spec.accepted["x"] == pytest.approx(2.0, abs=0.05)


def test_a_validation_error_aborts_the_run(synchronous_threads):
    panel = OptimizerRunnerPanel(build_run_spec=lambda: "nothing to run yet")

    panel._on_run(None)

    assert "nothing to run yet" in panel.status.value
    assert panel._fit_table.value == ""


def test_run_passes_the_chosen_optimizer_knobs_and_cancel_event(
    panel, fake_optimization, synchronous_threads
):
    calls = fake_optimization()
    panel._optimizer_picker.value = "U-NSGA-III"
    for field, value in zip(panel._knob_fields["U-NSGA-III"], (24, 7)):
        field.value = value

    panel._on_run(None)

    (call,) = calls
    assert (call["name"], call["kwargs"]) == ("U-NSGA-III", {"pop_size": 24, "n_max_gen": 7})
    assert call["x0"] == [0.0]
    assert call["cancel_event"] is panel._cancel_event


def test_cancel_sets_the_event_and_reports_a_cancel_not_an_error(
    panel, monkeypatch, synchronous_threads
):
    import cadetgui.widgets.estimation.optimizer_panel as optimizer_panel
    from cadetgui.estimation.optimizer_runner import OptimizerRunResult

    def cancelled_run(*args, cancel_event, **kwargs):
        panel._btn_cancel.click()
        assert cancel_event.is_set()
        return OptimizerRunResult({}, None, False, "Cancelled by user.", cancelled=True)

    monkeypatch.setattr(optimizer_panel, "run_optimization", cancelled_run)

    panel._on_run(None)

    assert "cancelled" in panel.status.value.lower()
    assert "error" not in panel.status.value
    assert not panel.running


def test_a_crashing_optimizer_is_reported_and_run_re_enabled(
    panel, monkeypatch, synchronous_threads
):
    import cadetgui.widgets.estimation.optimizer_panel as optimizer_panel

    def crash(*args, **kwargs):
        raise RuntimeError("synthetic optimizer crash")

    monkeypatch.setattr(optimizer_panel, "run_optimization", crash)

    panel._on_run(None)

    assert "synthetic optimizer crash" in panel.status.value
    assert not panel.running


@pytest.mark.parametrize(
    ("live_plot", "shown_gen", "redraws"), [(False, 0, 0), (True, 0, 1), (True, 1, 0)]
)
def test_progress_redraws_only_for_a_new_generation_with_live_plot_on(
    panel, run_spec, live_plot, shown_gen, redraws
):
    drawn = []
    spec = run_spec(preview_series=lambda x: drawn.append(x) or [])
    panel._progress["optimizer"] = optimizer(n_gen=1)
    panel._live_plot_checkbox.value = live_plot

    panel._progress_tick(time.monotonic(), spec, shown_gen)

    assert len(drawn) == redraws


@pytest.mark.parametrize("kind", ["series", "matplotlib", "error"])
def test_live_plot_draws_series_or_a_figure_and_shows_errors(panel, run_spec, kind):
    series = [{"name": "c", "times": [0.0, 1.0], "values": [0.0, 1.0]}]

    def boom(_x):
        raise RuntimeError("synthetic live plot failure")

    preview = {"series": lambda x: series, "matplotlib": lambda x: None, "error": boom}[kind]

    panel._redraw_live_plot(optimizer(), run_spec(preview_series=preview))

    if kind == "series":
        assert panel._live_chart.series == series
        assert panel._history_chart.series[0]["values"] == [1.0, 1.0]
    elif kind == "matplotlib":
        assert panel._live_plot_out.value
    else:
        assert "synthetic live plot failure" in panel._live_plot_error.value


@pytest.mark.parametrize(
    ("results", "convergence", "pairwise", "error"),
    [
        ({"n_var": 1}, True, False, ""),
        ({"n_var": 2}, True, True, ""),
        ({"n_gen": 0}, False, False, ""),
        ({"fail": True}, False, False, "synthetic analytics failure"),
    ],
)
def test_analytics_plot_what_the_run_supports(panel, results, convergence, pairwise, error):
    panel._progress["optimizer"] = optimizer(**results)

    panel._show_analytics_checkbox.value = True

    assert bool(panel._convergence_out.value) is convergence
    assert bool(panel._pairwise_out.value) is pairwise
    assert error in panel._analytics_error.value


@pytest.mark.slow
def test_cancel_stops_a_real_threaded_run(run_spec):
    panel = OptimizerRunnerPanel(build_run_spec=lambda: run_spec(delay=0.05))
    panel._knob_fields["Nelder-Mead"][0].value = 100_000
    threading.Timer(0.3, panel._btn_cancel.click).start()

    panel._on_run(None)

    deadline = time.monotonic() + 10
    while not run_spec.finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert run_spec.finished and run_spec.finished[0].cancelled
