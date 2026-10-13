"""Characterization stages and the step runner: setup, build, run, Pareto candidates, posterior."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.characterization.parameter_store import (
    ParameterSpec,
    ParameterStore,
    Provenance,
    check_chain,
)
from cadetgui.characterization.runner import (
    AVERAGE_TAG,
    Candidate,
    StepResult,
    StepSetup,
    build,
    current_best_average,
    default_optimizer,
    default_optimizer_knobs,
    estimated_simulations,
    fitted_variables,
    missing_requirements,
    pareto_candidates,
    posterior,
    run,
)
from cadetgui.characterization.stages import (
    STAGES,
    build_problem,
    describe_stage,
    write_targets,
)
from CADETProcess import CADETProcessError
from CADETProcess.characterization import setup_comparators
from CADETProcess.instruments import LCFlowSheet, PulseInjection
from CADETProcess.processModel import (
    ComponentSystem,
    LumpedRateModelWithPores,
    StericMassAction,
)
from CADETProcess.reference import ReferenceIO
from CADETProcess.simulator import Cadet

from characterization.synthetic import (
    DISPERSION,
    LENGTH,
    PRIOR,
    TRUE_DISPERSION,
    TRUTH,
    TUBING,
    make_comparison,
    store_with,
    synthetic_run,
)

BOUNDS = {f"{TUBING}_length": (0.2, 1.5), f"{TUBING}_axial_dispersion": (1e-7, 1e-4)}
PULSES = ("System pulse 1 (UV)", "System pulse 2 (UV)")
SALT_A = ComponentSystem(["Salt", "A"])


@pytest.fixture(scope="module")
def comparisons():
    """Two pulse runs through the same tubing at two flow rates."""
    a = make_comparison(PULSES[0])
    b = make_comparison(PULSES[1], overrides={"flow_rate": 2e-8, "cycle_time": 250.0})
    a.run = synthetic_run(a, seed=1)
    b.run = synthetic_run(b, seed=2)
    return [a, b]


@pytest.fixture
def setup(comparisons):
    return StepSetup(
        name="Extra-column volume", stage="tubing", options={"tubing": TUBING},
        comparisons=comparisons, bounds=BOUNDS,
    )


def front(x, f, objective_names=PULSES) -> StepResult:
    return StepResult(
        step="s", variable_names=["a", "b"], objective_names=list(objective_names),
        x=np.asarray(x, dtype=float), f=np.asarray(f, dtype=float), success=True,
        message="", cancelled=False, optimizer_name="U-NSGA-III", built=None,
    )


class TestStages:
    @pytest.mark.parametrize("stage_id, options", [
        ("tubing", {"tubing"}),
        ("pre_injection", set()),
        ("bed", {"include_particle_porosity"}),
        ("particles", {"include_axial_dispersion", "include_particle_porosity",
                       "include_film_diffusion", "include_pore_diffusion", "component_index"}),
        ("capacity", set()),
        ("adsorption", {"is_kinetic", "include_steric_factor", "include_film_diffusion",
                        "include_pore_diffusion", "component_index"}),
    ])
    def test_options_come_from_the_constructor_signature(self, stage_id, options):
        assert set(STAGES[stage_id].options) == options

    @pytest.mark.parametrize("stage_id, options, match", [
        ("tubing", {}, "tubing"),
        ("bed", {"bogus": True}, "bogus"),
        ("particles", {}, "include_"),
    ])
    def test_describe_stage_rejects_incomplete_or_unknown_options(self, stage_id, options, match):
        with pytest.raises(ValueError, match=match):
            describe_stage(stage_id, **options)

    @pytest.mark.parametrize("stage_id, options, names", [
        ("tubing", {"tubing": "tubing_pre_injection"},
         ["tubing_pre_injection_length", "tubing_pre_injection_axial_dispersion"]),
        ("bed", {}, ["bed_porosity", "axial_dispersion"]),
        ("bed", {"include_particle_porosity": True},
         ["bed_porosity", "axial_dispersion", "particle_porosity"]),
        ("particles", {"include_film_diffusion": True}, ["film_diffusion"]),
        ("capacity", {}, ["capacity"]),
        ("adsorption", {"is_kinetic": False}, ["characteristic_charge", "adsorption_rate"]),
    ])
    def test_variables_follow_the_options(self, stage_id, options, names):
        assert [v.name for v in describe_stage(stage_id, **options)] == names

    def test_kinetic_adsorption_has_dependent_helpers_without_write_targets(self):
        variables = describe_stage("adsorption", is_kinetic=True)
        by_name = {v.name: v for v in variables}
        assert not by_name["characteristic_charge"].is_dependent
        for name in ("adsorption_rate", "desorption_rate", "equilibrium_constant",
                     "kinetic_constant"):
            assert by_name[name].is_dependent
        targets = write_targets(variables)
        assert "equilibrium_constant" not in targets and "kinetic_constant" not in targets
        assert targets["adsorption_rate"] == "flow_sheet.column.binding_model.adsorption_rate"
        assert write_targets(describe_stage("particles", include_film_diffusion=True,
                                            component_index=1)) == {
            "film_diffusion": "flow_sheet.column.film_diffusion"
        }


def lrmp_pulse(name: str) -> PulseInjection:
    """A small LRMP + SMA pulse process."""
    flow_sheet = LCFlowSheet(
        SALT_A, sample_loop_volume=1e-7, ColumnModel=LumpedRateModelWithPores,
        BindingModel=StericMassAction, bypass_units=["tubing_post_column", "tubing_detectors"],
    )
    flow_sheet.mixer.init_liquid_volume = 1e-9
    flow_sheet.mixer.flow_rate = 1e-6
    for unit, length in (("tubing_pre_injection", 0.2), ("tubing_pre_column", 0.1)):
        tubing = flow_sheet[unit]
        tubing.length, tubing.diameter, tubing.axial_dispersion = length, 1e-3, 1e-7
    column = flow_sheet.column
    column.length, column.diameter = 0.1, 0.01
    column.bed_porosity, column.particle_porosity, column.particle_radius = 0.4, 0.6, 5e-5
    column.axial_dispersion, column.film_diffusion = 1e-7, [1e-5, 1e-5]
    column.discretization.ncol = 20
    binding = column.binding_model
    binding.is_kinetic = False
    binding.adsorption_rate, binding.desorption_rate = [0, 1.0], [1, 1]
    binding.characteristic_charge, binding.steric_factor = [0, 5.0], [0, 10.0]
    binding.capacity = 1000.0
    return PulseInjection(
        name, flow_sheet, c_buffer_a=[0, 0], c_sample=[0, 1.0], cycle_time=200.0, flow_rate=1e-6
    )


@pytest.fixture(scope="module")
def reference() -> ReferenceIO:
    outlet = Cadet().simulate(lrmp_pulse("reference")).solution.column.outlet
    return ReferenceIO("reference", outlet.time, outlet.solution, component_system=SALT_A)


def problem_for(stage, reference, **kwargs):
    process = lrmp_pulse(stage)
    (comparator,) = setup_comparators(
        process, reference, "column.outlet", metrics=["NRMSE"], components=["A"]
    )
    return build_problem(stage, process, comparator, Cadet(), **kwargs)


class TestBuildProblem:
    def test_bounds_frozen_variables_and_evaluation_at_the_reference(self, reference):
        problem = problem_for(
            "tubing", reference, options={"tubing": "tubing_pre_column"},
            bounds={"tubing_pre_column_length": (0.05, 0.2)},
            frozen={"tubing_pre_column_axial_dispersion"},
        )
        assert problem.variable_names == ["tubing_pre_column_length"]
        variable = problem.variables_dict["tubing_pre_column_length"]
        assert (variable.lb, variable.ub) == (0.05, 0.2)
        assert problem.n_callbacks == 0
        assert problem.evaluate_objectives([0.1]) == pytest.approx([0.0], abs=1e-6)

    def test_kinetic_dependent_variables_evaluate_and_cannot_be_frozen(self, reference):
        problem = problem_for("adsorption", reference, options={"is_kinetic": True},
                              frozen={"characteristic_charge"})
        assert problem.independent_variable_names == ["equilibrium_constant", "kinetic_constant"]
        assert problem.evaluate_objectives([1.0, 0.01])[0] < float("inf")
        with pytest.raises(CADETProcessError, match="kinetic_constant"):
            problem_for("adsorption", reference, options={"is_kinetic": True},
                        frozen={"kinetic_constant"})


class TestStepSetup:
    def test_provides_requires_and_feeds_check_chain(self, setup):
        assert setup.provides == [LENGTH, DISPERSION]
        check_chain([setup.step], store_with(PRIOR))
        setup.frozen = (f"{TUBING}_axial_dispersion",)
        assert setup.provides == [LENGTH]
        setup.requires = (LENGTH,)
        assert missing_requirements(setup, store_with({DISPERSION: {"A": 1e-6}})) == [LENGTH]
        assert missing_requirements(setup, store_with(PRIOR)) == []

    def test_from_dict_resolves_comparison_names(self, comparisons):
        raw = {
            "name": "Extra-column volume", "stage": "tubing", "options": {"tubing": TUBING},
            "comparisons": [PULSES[1]], "bounds": {f"{TUBING}_length": [0.1, 2.0]},
            "frozen": [],
        }
        setup = StepSetup.from_dict(raw, {c.name: c for c in comparisons})
        assert setup.comparisons == [comparisons[1]]
        assert setup.bounds == {f"{TUBING}_length": (0.1, 2.0)}

    def test_new_steps_are_sized_for_their_unfrozen_variables(self):
        assert StepSetup("s", "adsorption", {"is_kinetic": True}).optimizer["knobs"] == {
            "pop_size": 24, "n_max_gen": 12,
        }
        assert StepSetup("s", "bed", frozen=("bed_porosity",)).n_fitted_variables() == 1
        assert StepSetup("s", "tubing").n_fitted_variables() is None
        explicit = default_optimizer("Nelder-Mead", maxiter=5)
        assert StepSetup("s", "bed", optimizer=explicit).optimizer == explicit


@pytest.mark.parametrize("name, n_variables, expected", [
    ("U-NSGA-III", 1, {"pop_size": 16, "n_max_gen": 12}),
    ("U-NSGA-III", 3, {"pop_size": 24, "n_max_gen": 12}),
    ("Nelder-Mead", 0, {"maxiter": 200}),
    ("Nelder-Mead", 2, {"maxiter": 400}),
    ("Nelder-Mead", 7, {"maxiter": 1000}),
])
def test_default_optimizer_knobs_scale_with_the_fitted_variables(name, n_variables, expected):
    assert default_optimizer_knobs(name, n_variables) == expected


def test_estimated_simulations():
    assert default_optimizer()["knobs"] == {"pop_size": 0, "n_max_gen": 0}
    assert estimated_simulations(default_optimizer(n_variables=2), 3) == 16 * 12 * 3
    assert estimated_simulations(default_optimizer("Nelder-Mead", maxiter=300), 2) == 600
    assert estimated_simulations(default_optimizer(), 2) is None


def test_build_has_one_objective_per_comparison_and_rejects_duplicates(setup, comparisons):
    built = build(setup, store_with(PRIOR))
    assert [p.name for p in built.processes] == list(PULSES)
    assert built.problem.n_objectives == 2
    assert built.problem.independent_variable_names == list(BOUNDS)
    assert built.problem.lower_bounds_independent[0] == pytest.approx(0.2)
    duplicate = StepSetup("s", "tubing", {"tubing": TUBING}, [comparisons[0], comparisons[0]])
    with pytest.raises(ValueError, match="duplicate"):
        build(duplicate, store_with(PRIOR))


@pytest.mark.parametrize("x, f, names, tags, indices", [
    ([[1, 1], [2, 2], [3, 3]], [[0.1, 0.9], [0.4, 0.4], [0.9, 0.05]], PULSES,
     [(AVERAGE_TAG,), (f"best {PULSES[0]}",), (f"best {PULSES[1]}",)], [1, 0, 2]),
    ([[1, 1], [2, 2]], [[0.1, 0.2], [0.5, 0.1]], PULSES,
     [(AVERAGE_TAG, f"best {PULSES[0]}"), (f"best {PULSES[1]}",)], [0, 1]),
    ([[1, 1], [1, 1]], [[0.1, 0.9], [0.9, 0.1]], PULSES,
     [(AVERAGE_TAG, f"best {PULSES[0]}", f"best {PULSES[1]}")], None),
    ([[1, 1], [2, 2]], [[0.3], [0.2]], PULSES[:1], [(AVERAGE_TAG, f"best {PULSES[0]}")], [1]),
    (np.empty((0, 2)), np.empty((0, 2)), PULSES, [], []),
], ids=["three winners", "merged tags", "identical x", "single objective", "empty"])
def test_pareto_candidates(x, f, names, tags, indices):
    candidates = pareto_candidates(front(x, f, names))
    assert [set(c.tags) for c in candidates] == [set(t) for t in tags]
    if indices is not None:
        assert [c.index for c in candidates] == indices


def test_current_best_average_reads_the_running_front():
    optimizer = SimpleNamespace(results=None)
    assert current_best_average(optimizer) is None
    running = SimpleNamespace(
        x_independent=np.array([[0.3, 1e-7], [0.4, 2e-7], [0.5, 3e-7]]),
        f=np.array([[0.01, 0.9], [0.2, 0.2], [0.9, 0.01]]),
    )
    optimizer.results = SimpleNamespace(pareto_fronts=[running], meta_front=running)
    assert current_best_average(optimizer) == Candidate(1, (0.4, 2e-7), (0.2, 0.2), (AVERAGE_TAG,))


class TestPosterior:
    def test_writes_the_candidate_with_provenance(self, setup):
        store = store_with(PRIOR)
        candidate = Candidate(0, (TRUTH[LENGTH], TRUE_DISPERSION), (0.01, 0.02), (AVERAGE_TAG,))
        updated = posterior(setup, build(setup, store), store, candidate)

        assert updated.value(LENGTH) == pytest.approx(TRUTH[LENGTH])
        assert updated.value(DISPERSION)["SmallTracer"] == pytest.approx(TRUE_DISPERSION)
        assert store.value(LENGTH) == pytest.approx(PRIOR[LENGTH])
        assert (updated.step, updated.prior) == ("Extra-column volume", "test")
        provenance = updated.entries[LENGTH].provenance
        assert provenance.step == "Extra-column volume"
        assert provenance.source == ", ".join(PULSES)
        assert provenance.probe == "SmallTracer"
        assert provenance.metric == {f"{PULSES[0]}_NRMSE": 0.01, f"{PULSES[1]}_NRMSE": 0.02}

    def test_declares_specs_for_paths_the_store_has_not_seen(self, setup):
        store = ParameterStore().updated({}, Provenance(step="empty"))
        updated = posterior(setup, build(setup, store), store,
                            Candidate(0, (0.5, 1e-6), (0.1, 0.1), (AVERAGE_TAG,)))
        assert updated.spec(DISPERSION) == ParameterSpec(DISPERSION, species_indexed=True)
        assert updated.value(DISPERSION) == {"SmallTracer": pytest.approx(1e-6)}

    def test_reads_each_probe_from_its_own_process(self, study, periphery_posterior):
        prior = periphery_posterior.updated(
            {DISPERSION: {"SmallTracer": 4.5e-7, "LargeTracer": 4.5e-7}}, Provenance(step="t")
        )
        setup = study.steps[1]
        built = build(setup, prior)
        problem = built.problem
        assert list(problem.independent_variable_names) == fitted_variables(
            describe_stage(setup.stage, **setup.options), setup.frozen
        )
        x = tuple((lb + ub) / 2 for lb, ub in zip(problem.lower_bounds_independent,
                                                  problem.upper_bounds_independent))
        store = posterior(setup, built, prior, Candidate(0, x, (0.0,) * 4, (AVERAGE_TAG,)))
        assert set(store.value("flow_sheet.column.axial_dispersion")) == {
            "SmallTracer", "LargeTracer",
        }


def coarsen(built, ncol: int) -> None:
    for process in built.processes:
        process.flow_sheet[TUBING].discretization.ncol = ncol


@pytest.mark.slow
def test_cancel_before_the_first_generation_returns_an_empty_front(setup):
    store = store_with(PRIOR)
    built = build(setup, store)
    coarsen(built, 20)
    cancel = threading.Event()
    cancel.set()
    result = run(setup, store, optimizer_kwargs={"pop_size": 4, "n_max_gen": 2},
                 cancel_event=cancel, built=built)
    assert result.cancelled and not result.success
    assert result.x.shape == (0, 2)
    assert pareto_candidates(result) == []


@pytest.mark.slow
def test_tubing_step_recovers_the_length(setup):
    store = store_with(PRIOR)
    built = build(setup, store)
    coarsen(built, 40)
    result = run(setup, store, optimizer_kwargs={"pop_size": 16, "n_max_gen": 8}, built=built)
    assert result.success, result.message
    assert result.f.shape[1] == 2 and len(result.x) == len(result.f) > 0

    best = next(c for c in pareto_candidates(result) if AVERAGE_TAG in c.tags)
    updated = posterior(setup, built, store, best)
    assert updated.value(LENGTH) == pytest.approx(TRUTH[LENGTH], rel=0.1)
