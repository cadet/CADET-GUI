"""Building an estimation problem from a configuration, a dataset and chosen parameters."""
from __future__ import annotations

import copy
import threading

import numpy as np
import pytest
from cadetgui.estimation.optimizer_runner import OPTIMIZERS, OptimizerSpec
from cadetgui.estimation.parameter_estimation import (
    build_estimation_problem,
    build_reference,
    list_fittable_parameters,
    run_estimation,
    simulate_at,
)
from cadetgui.instrument.signals import measurable_signal_options
from cadetgui.parameters.specs import FieldSpec
from cadetgui.process_model.signals import list_signal_ports
from cadetgui.process_model.simulation import run_process

FIELDS = [
    FieldSpec("total_porosity", "float", "Total porosity", 0.72, min=0.0, max=1.0),
    FieldSpec("is_kinetic", "bool", "Is kinetic", True),
    FieldSpec(
        "adsorption_rate", "float_list", "Adsorption rate", [1.0, 2.0],
        min=0.0, component_names=("Salt", "Protein"),
    ),
]
VALUES = {"total_porosity": 0.72, "is_kinetic": True, "adsorption_rate": [1.0, 2.0]}


def test_fittable_parameters_are_numeric_fields_one_per_component_with_bounds():
    porosity, salt, protein = list_fittable_parameters("binding", FIELDS, VALUES)

    assert (porosity.name, porosity.component_index, porosity.lb, porosity.ub) == (
        "total_porosity", None, 0.0, 1.0,
    )
    assert [p.component_index for p in (salt, protein)] == [0, 1]
    assert [p.current_value for p in (salt, protein)] == [1.0, 2.0]
    assert "Protein" in protein.label
    assert (salt.lb, salt.ub) == (0.0, 10.0)  # no registered max: 10x the current value


def test_reference_converts_minutes_to_seconds_and_tags_its_component():
    ref = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0], component_name="B")

    np.testing.assert_allclose(ref.time, [0.0, 60.0, 120.0, 180.0])
    assert ref.component_system.names == ["B"]


def test_problem_maps_each_selection_to_a_transformed_variable_on_a_detached_copy(configuration):
    configuration.components = ["A", "B"]
    column_form, binding_form = configuration.column_form, configuration.binding_form
    params = list_fittable_parameters(
        "column", column_form.spec.fields, column_form.collect_values()
    ) + list_fittable_parameters("binding", binding_form.spec.fields, binding_form.collect_values())
    porosity = next(i for i, p in enumerate(params) if p.name == "total_porosity")
    rate_b = next(
        i for i, p in enumerate(params) if p.name == "adsorption_rate" and p.component_index == 1
    )
    process = configuration.process
    reference = build_reference("m", np.arange(5.0), [0.0, 1.0, 0.0, 0.0, 0.0], component_name="B")

    problem, working = build_estimation_problem(
        process, column_form.built, params, [porosity, rate_b], reference, "outlet.inlet",
        component_name="B",
    )
    problem.set_variables([0.5, 0.3])

    assert problem.variable_names == [f"var_{porosity}", f"var_{rate_b}"]
    assert all(v.normalization == "auto" for v in problem.variables)
    assert [(v.lb, v.ub) for v in problem.variables] == [
        (params[i].lb, params[i].ub) for i in (porosity, rate_b)
    ]
    assert working.flow_sheet.column.total_porosity == 0.5
    assert working.flow_sheet.column.binding_model.adsorption_rate[1] == 0.3
    assert process.flow_sheet.column.total_porosity == params[porosity].current_value
    assert problem.n_objectives == 1


def test_simulate_at_matches_a_manual_edit_and_leaves_the_process_alone(porosity_fit):
    process, column, params, index = porosity_fit
    before = column.total_porosity

    result = simulate_at(process, column, params, [index], [0.5])

    manual = copy.deepcopy(process)
    manual.flow_sheet.units_dict["column"].total_porosity = 0.5
    np.testing.assert_allclose(
        result.solution.outlet.inlet.solution,
        run_process(manual).solution.outlet.inlet.solution,
    )
    assert column.total_porosity == before


def test_run_estimation_without_a_selection_does_not_run(porosity_fit):
    process, column, params, _ = porosity_fit

    result = run_estimation(
        process, column, params, [], None, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={}, starts=[],
    )

    assert (result.success, result.fitted) == (False, {})


def test_run_estimation_hands_starts_and_optimizer_over_before_optimizing(
    porosity_fit, monkeypatch
):
    process, column, params, index = porosity_fit
    reference = build_reference("raw", np.arange(4.0), np.arange(4.0))
    seen = {}

    class StoppingOptimizer:
        def __init__(self, **kwargs):
            pass

        def optimize(self, problem, x0, **kwargs):
            seen.update(x0=x0, ready_first="optimizer" in seen)
            raise RuntimeError("stop before solving")

    monkeypatch.setitem(OPTIMIZERS, "Nelder-Mead", OptimizerSpec(StoppingOptimizer, (), False))

    result = run_estimation(
        process, column, params, [index], reference, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={}, starts=[0.42],
        on_optimizer_ready=lambda opt: seen.update(optimizer=opt),
    )

    assert seen["x0"] == [0.42] and seen["ready_first"]
    assert not result.success and "stop before solving" in result.message


def test_signal_options_are_the_measurable_subset_of_the_ports(configuration):
    process = configuration.process

    options = measurable_signal_options(process)

    assert options[0] == ("Outlet", ("outlet", "inlet"))
    assert {value for _, value in options} < {value for _, value in list_signal_ports(process)}


@pytest.mark.slow
def test_real_fit_recovers_the_porosity_without_touching_the_original(
    porosity_fit, total_reference
):
    process, column, params, index = porosity_fit
    true_value = column.total_porosity

    result = run_estimation(
        process, column, params, [index], total_reference(process), "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 30}, starts=[true_value],
    )

    assert result.success
    assert result.fitted[index] == pytest.approx(true_value, abs=0.05)
    assert result.fitted_process is not process
    assert column.total_porosity == true_value


@pytest.mark.slow
def test_real_fit_stops_early_when_cancelled(porosity_fit, total_reference):
    process, column, params, index = porosity_fit
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()

    result = run_estimation(
        process, column, params, [index], total_reference(process), "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 500}, starts=[0.3],
        cancel_event=cancel,
    )

    assert result.cancelled and not result.success
