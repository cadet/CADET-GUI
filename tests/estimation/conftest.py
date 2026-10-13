"""Estimation fixtures: a configuration, fittable parameters, data upload, trivial problems."""
from __future__ import annotations

import datetime as dt
import time
import warnings

import cadetgui.widgets.estimation.optimizer_panel as optimizer_panel
import pytest
from cadetgui.estimation.optimizer_runner import OptimizerRunResult
from cadetgui.estimation.parameter_estimation import (
    build_reference,
    list_fittable_parameters,
)
from cadetgui.process_model.simulation import run_process
from cadetgui.widgets.estimation import ParameterEstimationWidget
from CADETProcess.optimization import OptimizationProblem

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture
def configuration(instrument_and_configuration):
    """A default, committed ConfigurationWidget."""
    return instrument_and_configuration[1]


@pytest.fixture
def porosity_fit(configuration):
    """`(process, column, params, index)` for fitting the configured column's total porosity."""
    form = configuration.column_form
    params = list_fittable_parameters("column", form.spec.fields, form.collect_values())
    index = next(i for i, p in enumerate(params) if p.name == "total_porosity")
    return configuration.process, form.built, params, index


def measured_csv(solution, column=None, scale=1.0) -> str:
    """A `time (min), signal` CSV of a simulated outlet: one component or the total."""
    signal = solution.solution.sum(axis=1) if column is None else solution.solution[:, column]
    rows = [f"{t / 60.0},{s * scale}" for t, s in zip(solution.time[::10], signal[::10])]
    return "\n".join(["time,signal", *rows])


def upload_csv(data_widget, filename: str, csv_text: str) -> None:
    """Upload `csv_text` through the DataImportWidget's file picker."""
    content = memoryview(csv_text.encode("utf-8"))
    data_widget._upload.value = (
        {
            "name": filename, "type": "text/csv", "size": len(content),
            "last_modified": dt.datetime.now(), "content": content,
        },
    )


def add_parameter(widget: ParameterEstimationWidget, name: str) -> int:
    """Add the parameter called `name` through the Add-parameter picker; return its index."""
    space = widget.param_space
    index = next(i for i, p in enumerate(space.params) if p.name == name)
    space._param_add_picker.value = space._param_key(space.params[index])
    space._btn_add_param.click()
    return index


@pytest.fixture
def upload():
    """`upload(data_widget, filename, csv_text)`."""
    return upload_csv


@pytest.fixture
def add_param():
    """`add_param(widget, name) -> index`."""
    return add_parameter


@pytest.fixture
def csv_of():
    """`csv_of(solution, column=None, scale=1.0)`: a measured CSV of a simulated outlet."""
    return measured_csv


@pytest.fixture
def total_reference():
    """Return a reference of `process`'s summed outlet signal."""
    def make(process):
        sol = run_process(process).solution.outlet.inlet
        return build_reference("measured", sol.time / 60.0, sol.solution.sum(axis=1))
    return make


@pytest.fixture
def bound(configuration):
    """`(configuration, estimation widget)` bound together."""
    widget = ParameterEstimationWidget()
    widget.bind_to_config(configuration)
    return configuration, widget


@pytest.fixture
def ready(bound):
    """A bound estimation widget with a measured dataset picked and porosity added."""
    configuration, widget = bound
    unit, port = widget._signal_picker.value
    solution = widget._display_result.solution[unit][port]
    upload_csv(widget.data, "measured.csv", measured_csv(solution, scale=1.05))
    widget._dataset_picker.selected_index = 0
    add_parameter(widget, "total_porosity")
    widget._runner._knob_fields["Nelder-Mead"][0].value = 20
    return configuration, widget


@pytest.fixture
def fake_optimization(monkeypatch):
    """Replace the panel's optimizer by a recorder that returns `x_best` at once."""
    calls: list[dict] = []

    def install(x_best=None, **result_kwargs):
        def fake(problem, optimizer_name, optimizer_kwargs, x0, **kwargs):
            calls.append(dict(problem=problem, name=optimizer_name,
                              kwargs=dict(optimizer_kwargs), x0=list(x0), **kwargs))
            if x_best is None:
                return OptimizerRunResult({}, None, False, "stopped", **result_kwargs)
            return OptimizerRunResult(dict(x_best), 0.0, True, "Optimization finished.")
        monkeypatch.setattr(optimizer_panel, "run_optimization", fake)
        return calls

    return install


@pytest.fixture
def trivial_problem():
    """Build a pure-Python quadratic with its minimum at x=2 (and y=-1); optionally slow."""
    def make(n_var: int = 2, delay: float = 0.0) -> OptimizationProblem:
        def objective(v):
            if delay:
                time.sleep(delay)
            return (v[0] - 2.0) ** 2 + sum((x + 1.0) ** 2 for x in v[1:])

        problem = OptimizationProblem("trivial")
        for name in ("x", "y")[:n_var]:
            problem.add_variable(name, lb=-5, ub=5, transform="auto")
        problem.add_objective(objective)
        return problem
    return make
