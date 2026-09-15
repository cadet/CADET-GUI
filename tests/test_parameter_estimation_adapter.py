from __future__ import annotations

import threading
import time
import warnings

import numpy as np
import pytest
from cadetgui.cadetprocessadapter import FieldSpec
from cadetgui.parameter_estimation import (
    build_reference,
    calibrate_reference,
    list_fittable_parameters,
    run_estimation,
    simulate_at,
)
from cadetgui.simulation import run_process
from cadetgui.widgets.composite import ConfigurationWidget

warnings.filterwarnings("ignore", category=UserWarning)


def built_widget() -> ConfigurationWidget:
    return ConfigurationWidget()  # auto-commits its defaults on construction


FIELDS = [
    FieldSpec("total_porosity", "float", "Total porosity", 0.72, min=0.0, max=1.0),
    FieldSpec("is_kinetic", "bool", "Is kinetic", True),
    FieldSpec(
        "adsorption_rate", "float_list", "Adsorption rate", [1.0, 2.0],
        min=0.0, component_names=("Salt", "Protein"),
    ),
]
VALUES = {"total_porosity": 0.72, "is_kinetic": True, "adsorption_rate": [1.0, 2.0]}


def test_list_fittable_parameters_skips_non_numeric_kinds():
    params = list_fittable_parameters("column", FIELDS, VALUES)

    assert [p.name for p in params] == ["total_porosity", "adsorption_rate", "adsorption_rate"]


def test_list_fittable_parameters_expands_float_list_per_component():
    params = list_fittable_parameters("binding", FIELDS, VALUES)
    rate_params = [p for p in params if p.name == "adsorption_rate"]

    assert [p.component_index for p in rate_params] == [0, 1]
    assert [p.current_value for p in rate_params] == [1.0, 2.0]
    assert "Salt" in rate_params[0].label
    assert "Protein" in rate_params[1].label


def test_list_fittable_parameters_fills_in_missing_bounds():
    params = list_fittable_parameters("column", FIELDS, VALUES)
    porosity = next(p for p in params if p.name == "total_porosity")
    rate0 = next(p for p in params if p.component_index == 0)

    assert (porosity.lb, porosity.ub) == (0.0, 1.0)  # registered bounds, kept as-is
    assert rate0.lb == 0.0
    assert rate0.ub == 10.0 * rate0.current_value  # no registered max -> 10x current


def test_calibrate_reference_none_returns_the_same_object():
    ref = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])

    assert calibrate_reference(ref, "none") is ref


def test_calibrate_reference_beer_lambert_divides_by_extinction_times_path_length():
    ref = build_reference("uv", [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 30.0, 40.0])

    calibrated = calibrate_reference(
        ref, "beer_lambert", extinction_coefficient=2.0, path_length=5.0
    )

    assert np.allclose(calibrated.solution[:, 0], ref.solution[:, 0] / 10.0)


def test_calibrate_reference_normalize_area_matches_the_target_area():
    t = np.linspace(0, 10, 50)
    ref = build_reference("uv", t, np.exp(-((t - 5) ** 2)))

    calibrated = calibrate_reference(ref, "normalize_area", target_area=3.0)

    assert np.isclose(calibrated.fraction_mass()[0], 3.0)


def test_calibrate_reference_rejects_an_unknown_method():
    ref = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])

    with pytest.raises(ValueError):
        calibrate_reference(ref, "not_a_real_method")  # type: ignore[arg-type]


def test_build_reference_without_a_component_name_is_unnamed():
    ref = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])

    assert ref.n_comp == 1
    assert ref.component_system.names == ["0"]  # CADET-Process's own auto-generated default


def test_build_reference_tags_the_named_component():
    ref = build_reference(
        "raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0], component_name="Component 2"
    )

    assert ref.component_system.names == ["Component 2"]


@pytest.mark.parametrize("method,kwargs", [
    ("beer_lambert", {"extinction_coefficient": 2.0, "path_length": 1.0}),
    ("normalize_area", {"target_area": 3.0}),
])
def test_calibrate_reference_preserves_the_component_name(method, kwargs):
    # Regression: apply_beer_lambert/normalize_area build a fresh ReferenceIO
    # internally and don't carry the input's component_system over -- a
    # `component_name` set via build_reference must survive calibration.
    ref = build_reference(
        "raw", np.linspace(0, 10, 20), np.linspace(1, 2, 20), component_name="Component 2"
    )

    calibrated = calibrate_reference(ref, method, **kwargs)

    assert calibrated.component_system.names == ["Component 2"]


def test_run_estimation_with_no_selection_does_not_run():
    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )

    # `reference` is never touched when nothing is selected -- None is fine here.
    result = run_estimation(
        process, column, params, [], None, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 5}, starts=[],
    )

    assert result.success is False
    assert result.fitted == {}


def test_run_estimation_uses_explicit_starts_as_x0(monkeypatch):
    import cadetgui.parameter_estimation as pe

    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    reference = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")
    captured = {}

    class _FakeOptimizer:
        def __init__(self, maxiter):
            pass

        def optimize(self, problem, x0, **kwargs):
            captured["x0"] = x0
            raise RuntimeError("stop before an actual solve")

    # `OPTIMIZERS["Nelder-Mead"].factory` already captured the real class by
    # the time this test runs -- patching the module-level `pe.NelderMead`
    # name wouldn't affect it, the registry entry itself must be replaced.
    monkeypatch.setitem(
        pe.OPTIMIZERS, "Nelder-Mead",
        pe.OptimizerSpec(factory=_FakeOptimizer, knobs=(), is_population_based=False),
    )

    starts = [0.42]
    run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 5}, starts=starts,
    )

    assert captured["x0"] == starts


def test_run_estimation_calls_on_optimizer_ready_before_optimizing(monkeypatch):
    import cadetgui.parameter_estimation as pe

    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    reference = build_reference("raw", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")
    seen = {}

    class _FakeOptimizer:
        def __init__(self, maxiter):
            self.results = "not-yet-populated-marker"

        def optimize(self, problem, x0, **kwargs):
            # on_optimizer_ready must have already fired by the time we get here.
            assert seen.get("optimizer") is self
            raise RuntimeError("stop before an actual solve")

    monkeypatch.setitem(
        pe.OPTIMIZERS, "Nelder-Mead",
        pe.OptimizerSpec(factory=_FakeOptimizer, knobs=(), is_population_based=False),
    )

    run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 5}, starts=[0.5],
        on_optimizer_ready=lambda opt: seen.update(optimizer=opt),
    )

    assert isinstance(seen["optimizer"], _FakeOptimizer)


def test_simulate_at_writes_values_onto_an_independent_copy():
    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    original_porosity = column.total_porosity
    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")

    result = simulate_at(process, column, params, [porosity_idx], [0.5])

    assert column.total_porosity == original_porosity  # caller's process untouched
    assert result.solution.outlet.inlet.solution.shape[1] == len(cw._components.value)

    # Compare against a hand-built simulation at the same value -- same curve.
    import copy as _copy

    from cadetgui.simulation import run_process
    manual = _copy.deepcopy(process)
    manual.flow_sheet.units_dict["column"].total_porosity = 0.5
    expected = run_process(manual)

    np.testing.assert_allclose(
        result.solution.outlet.inlet.solution, expected.solution.outlet.inlet.solution
    )


@pytest.mark.slow
def test_run_estimation_recovers_a_perturbed_parameter_without_touching_the_original():
    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    original_porosity = column.total_porosity

    baseline = run_process(process)
    sol = baseline.solution.outlet.inlet
    total = sol.solution.sum(axis=1)
    reference = build_reference("measured", sol.time / 60.0, total)

    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")

    result = run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 30},
        starts=[original_porosity],
    )

    assert result.success
    assert np.isclose(result.fitted[porosity_idx], original_porosity, atol=0.05)
    assert result.fitted_process is not process
    assert column.total_porosity == original_porosity  # the live object is untouched


@pytest.mark.slow
def test_run_estimation_recovers_a_parameter_with_u_nsga_iii():
    # Same recovery exercise as the Nelder-Mead version above, but through
    # the population-based optimizer -- confirms run_estimation is genuinely
    # optimizer-agnostic (same OptimizationProblem/variable registration/
    # optimize() call, only the OPTIMIZERS[...] factory differs) rather than
    # something that happens to work for Nelder-Mead specifically.
    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    original_porosity = column.total_porosity

    baseline = run_process(process)
    sol = baseline.solution.outlet.inlet
    total = sol.solution.sum(axis=1)
    reference = build_reference("measured", sol.time / 60.0, total)

    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")

    result = run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name="U-NSGA-III",
        optimizer_kwargs={"pop_size": 16, "n_max_gen": 30},
        starts=[original_porosity],
    )

    assert result.success
    assert np.isclose(result.fitted[porosity_idx], original_porosity, atol=0.05)
    assert result.fitted_process is not process
    assert column.total_porosity == original_porosity  # the live object is untouched


@pytest.mark.slow
def test_run_estimation_with_a_component_name_ignores_other_components():
    # A reference built from just "Component 2" should recover the same fit
    # whether "Component 1" is perturbed or not -- it's never looked at.
    cw = built_widget()
    process, column = cw.process, cw._column_form.built
    original_porosity = column.total_porosity

    baseline = run_process(process)
    sol = baseline.solution.outlet.inlet
    comp2 = sol.solution[:, 1]
    reference = build_reference(
        "measured", sol.time / 60.0, comp2, component_name="Component 2"
    )

    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")

    result = run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name="Nelder-Mead", optimizer_kwargs={"maxiter": 30},
        starts=[original_porosity], component_name="Component 2",
    )

    assert result.success
    assert np.isclose(result.fitted[porosity_idx], original_porosity, atol=0.05)


@pytest.mark.slow
@pytest.mark.parametrize(
    "optimizer_name,optimizer_kwargs,max_elapsed",
    [
        # Nelder-Mead evaluates one candidate per iteration, so cancel fires
        # within roughly one simulation.
        ("Nelder-Mead", {"maxiter": 500}, 15),
        # U-NSGA-III evaluates its whole population before the per-generation
        # cancel check is next reached (confirmed: PymooInterface._run calls
        # `algorithm.evaluator.eval(problem, pop)` for the entire population
        # before `run_post_processing`) -- a small pop_size keeps this test
        # fast while still exercising that real latency, not just Nelder-Mead's.
        ("U-NSGA-III", {"pop_size": 8, "n_max_gen": 200}, 30),
    ],
)
def test_run_estimation_stops_early_when_cancelled(optimizer_name, optimizer_kwargs, max_elapsed):
    # Real optimize() call, real cancellation, no mocking -- confirms the
    # solver-agnostic cancel hook (patches `run_post_processing`, shared by
    # every OptimizerBase subclass) actually aborts the run for *both*
    # optimizer families, not just Nelder-Mead specifically. Raising from
    # inside an evaluator or an OptimizationProblem.add_callback() callback
    # does *not* abort either one -- CADET-Process's evaluation pipeline
    # swallows those by design, confirmed separately.
    cw = built_widget()
    process, column = cw.process, cw._column_form.built

    baseline = run_process(process)
    sol = baseline.solution.outlet.inlet
    total = sol.solution.sum(axis=1)
    reference = build_reference("measured", sol.time / 60.0, total)

    params = list_fittable_parameters(
        "column", cw._column_form.spec.fields, cw._column_form.collect_values()
    )
    porosity_idx = next(i for i, p in enumerate(params) if p.name == "total_porosity")

    cancel_event = threading.Event()

    def _cancel_soon() -> None:
        time.sleep(0.3)
        cancel_event.set()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    start_time = time.monotonic()
    result = run_estimation(
        process, column, params, [porosity_idx], reference, "outlet.inlet",
        optimizer_name=optimizer_name, optimizer_kwargs=optimizer_kwargs,
        starts=[0.3],  # deliberately far from the optimum, needs many iterations
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - start_time

    assert result.cancelled
    assert not result.success
    assert "cancelled" in result.message.lower()
    assert elapsed < max_elapsed  # stopped promptly, not after the full run
    assert column.total_porosity == 0.72  # the live object is still untouched
