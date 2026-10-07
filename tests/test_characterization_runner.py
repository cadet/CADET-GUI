from __future__ import annotations

import threading
import warnings
from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.characterization_runner import (
    AVERAGE_TAG,
    Candidate,
    StepResult,
    StepSetup,
    build,
    current_best_average,
    default_optimizer,
    default_optimizer_knobs,
    estimated_simulations,
    missing_requirements,
    pareto_candidates,
    posterior,
    run,
)
from cadetgui.parameter_store import (
    ParameterSpec,
    ParameterStore,
    Provenance,
    check_chain,
)

from test_comparison import (
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

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

BOUNDS = {
    f"{TUBING}_length": (0.2, 1.5),
    f"{TUBING}_axial_dispersion": (1e-7, 1e-4),
}


@pytest.fixture(scope="module")
def comparisons():
    """Two pulse runs through the same tubing at two flow rates."""
    a = make_comparison("System pulse 1 (UV)")
    b = make_comparison("System pulse 2 (UV)", overrides={"flow_rate": 2e-8, "cycle_time": 250.0})
    a.run = synthetic_run(a, seed=1)
    b.run = synthetic_run(b, seed=2)
    return [a, b]


@pytest.fixture
def setup(comparisons):
    return StepSetup(
        name="Extra-column volume", stage="tubing", options={"tubing": TUBING},
        comparisons=comparisons, bounds=BOUNDS,
    )


def coarsen(built, ncol: int = 20) -> None:
    for process in built.processes:
        process.flow_sheet[TUBING].discretization.ncol = ncol


def front(x, f, objective_names=("System pulse 1 (UV)", "System pulse 2 (UV)")) -> StepResult:
    return StepResult(
        step="s", variable_names=["a", "b"], objective_names=list(objective_names),
        x=np.asarray(x, dtype=float), f=np.asarray(f, dtype=float), success=True,
        message="", cancelled=False, optimizer_name="U-NSGA-III", built=None,
    )


class TestStepSetup:
    def test_provides_the_stage_write_targets(self, setup):
        assert setup.provides == [LENGTH, DISPERSION]

    def test_frozen_variables_are_not_provided(self, setup):
        setup.frozen = (f"{TUBING}_axial_dispersion",)
        assert setup.provides == [LENGTH]

    def test_missing_requirements_are_reported_not_raised(self, setup):
        setup.requires = (LENGTH,)
        assert missing_requirements(setup, store_with({DISPERSION: {"A": 1e-6}})) == [LENGTH]
        assert missing_requirements(setup, store_with(PRIOR)) == []

    def test_step_feeds_check_chain(self, setup):
        check_chain([setup.step], store_with(PRIOR))

    def test_from_dict_resolves_comparison_names(self, comparisons):
        raw = {
            "name": "Extra-column volume",
            "stage": "tubing",
            "options": {"tubing": TUBING},
            "comparisons": ["System pulse 2 (UV)"],
            "bounds": {f"{TUBING}_length": [0.1, 2.0]},
            "frozen": [],
        }
        setup = StepSetup.from_dict(raw, {c.name: c for c in comparisons})
        assert setup.comparisons == [comparisons[1]]
        assert setup.bounds == {f"{TUBING}_length": (0.1, 2.0)}


class TestBuild:
    def test_one_objective_per_comparison(self, setup):
        built = build(setup, store_with(PRIOR))
        assert [p.name for p in built.processes] == ["System pulse 1 (UV)", "System pulse 2 (UV)"]
        assert built.problem.n_objectives == 2
        assert built.problem.independent_variable_names == [
            f"{TUBING}_length", f"{TUBING}_axial_dispersion",
        ]
        assert built.problem.lower_bounds_independent[0] == pytest.approx(0.2)

    def test_duplicate_comparison_names_raise(self, comparisons):
        setup = StepSetup("s", "tubing", {"tubing": TUBING}, [comparisons[0], comparisons[0]])
        with pytest.raises(ValueError, match="duplicate"):
            build(setup, store_with(PRIOR))


class TestParetoCandidates:
    def test_average_and_each_objective_winner(self):
        result = front(
            x=[[1, 1], [2, 2], [3, 3]],
            f=[[0.1, 0.9], [0.4, 0.4], [0.9, 0.05]],
        )
        candidates = pareto_candidates(result)
        assert [c.tags for c in candidates] == [
            (AVERAGE_TAG,), ("best System pulse 1 (UV)",), ("best System pulse 2 (UV)",),
        ]
        assert [c.index for c in candidates] == [1, 0, 2]
        assert candidates[1].f == (0.1, 0.9)

    def test_duplicates_merge_their_tags(self):
        result = front(x=[[1, 1], [2, 2]], f=[[0.1, 0.2], [0.5, 0.1]])
        candidates = pareto_candidates(result)
        assert [c.tags for c in candidates] == [
            (AVERAGE_TAG, "best System pulse 1 (UV)"),
            ("best System pulse 2 (UV)",),
        ]

    def test_identical_x_at_different_rows_merge(self):
        result = front(x=[[1, 1], [1, 1]], f=[[0.1, 0.9], [0.9, 0.1]])
        (candidate,) = pareto_candidates(result)
        assert set(candidate.tags) == {
            AVERAGE_TAG, "best System pulse 1 (UV)", "best System pulse 2 (UV)",
        }

    def test_single_objective_gives_one_candidate(self):
        result = front(
            x=[[1, 1], [2, 2]], f=[[0.3], [0.2]], objective_names=["System pulse 1 (UV)"],
        )
        (candidate,) = pareto_candidates(result)
        assert candidate.tags == (AVERAGE_TAG, "best System pulse 1 (UV)")
        assert candidate.index == 1

    def test_empty_front_gives_none(self):
        assert pareto_candidates(front(np.empty((0, 2)), np.empty((0, 2)))) == []


class TestPosterior:
    def test_writes_the_candidate_with_provenance(self, setup):
        store = store_with(PRIOR)
        built = build(setup, store)
        candidate = Candidate(
            index=0, x=(TRUTH[LENGTH], TRUE_DISPERSION), f=(0.01, 0.02), tags=(AVERAGE_TAG,),
        )
        updated = posterior(setup, built, store, candidate)

        assert updated.value(LENGTH) == pytest.approx(TRUTH[LENGTH])
        assert updated.value(DISPERSION) == {
            "SmallTracer": pytest.approx(TRUE_DISPERSION), "A": TRUE_DISPERSION,
            "B": TRUE_DISPERSION,
        }
        assert store.value(LENGTH) == pytest.approx(PRIOR[LENGTH])
        assert updated.step == "Extra-column volume"
        assert updated.prior == "test"

        provenance = updated.entries[LENGTH].provenance
        assert provenance.step == "Extra-column volume"
        assert provenance.source == "System pulse 1 (UV), System pulse 2 (UV)"
        assert provenance.probe == "SmallTracer"
        assert provenance.model is None
        assert provenance.metric == {
            "System pulse 1 (UV)_NRMSE": 0.01,
            "System pulse 2 (UV)_NRMSE": 0.02,
        }

    def test_declares_specs_for_paths_the_store_has_not_seen(self, setup):
        store = ParameterStore().updated({}, Provenance(step="empty"))
        built = build(setup, store)
        candidate = Candidate(0, (0.5, 1e-6), (0.1, 0.1), (AVERAGE_TAG,))
        updated = posterior(setup, built, store, candidate)
        assert updated.spec(LENGTH) == ParameterSpec(LENGTH)
        assert updated.spec(DISPERSION) == ParameterSpec(DISPERSION, species_indexed=True)
        assert updated.value(DISPERSION) == {"SmallTracer": pytest.approx(1e-6)}
        assert updated.value(LENGTH) == pytest.approx(0.5)


@pytest.mark.slow
def test_cancel_before_the_first_generation_returns_an_empty_front(setup):
    store = store_with(PRIOR)
    built = build(setup, store)
    coarsen(built)
    cancel = threading.Event()
    cancel.set()
    result = run(
        setup, store, optimizer_kwargs={"pop_size": 4, "n_max_gen": 2},
        cancel_event=cancel, built=built,
    )
    assert result.cancelled
    assert not result.success
    assert result.x.shape == (0, 2)
    assert pareto_candidates(result) == []


@pytest.mark.slow
def test_tubing_step_recovers_the_length(setup):
    """Two comparisons, U-NSGA-III, small budget: the best-average length is within 10 %."""
    store = store_with(PRIOR)
    built = build(setup, store)
    coarsen(built, ncol=40)
    result = run(
        setup, store, optimizer_kwargs={"pop_size": 16, "n_max_gen": 8}, built=built,
    )
    assert result.success, result.message
    assert result.f.shape[1] == 2
    assert len(result.x) == len(result.f) > 0

    candidates = pareto_candidates(result)
    best = next(c for c in candidates if AVERAGE_TAG in c.tags)
    updated = posterior(setup, built, store, best)
    assert updated.value(LENGTH) == pytest.approx(TRUTH[LENGTH], rel=0.1)
    assert set(updated.entries[LENGTH].provenance.metric) == {
        "System pulse 1 (UV)_NRMSE",
        "System pulse 2 (UV)_NRMSE",
    }


@pytest.mark.parametrize(
    ("name", "n_variables", "expected"),
    [
        ("U-NSGA-III", 1, {"pop_size": 16, "n_max_gen": 12}),
        ("U-NSGA-III", 3, {"pop_size": 24, "n_max_gen": 12}),
        ("Nelder-Mead", 0, {"maxiter": 200}),
        ("Nelder-Mead", 2, {"maxiter": 400}),
        ("Nelder-Mead", 7, {"maxiter": 1000}),
    ],
)
def test_default_optimizer_knobs_scale_with_the_fitted_variables(name, n_variables, expected):
    assert default_optimizer_knobs(name, n_variables) == expected


def test_default_optimizer_sizes_only_when_given_the_variable_count():
    assert default_optimizer()["knobs"] == {"pop_size": 0, "n_max_gen": 0}
    assert default_optimizer(n_variables=3, n_max_gen=5)["knobs"] == {
        "pop_size": 24, "n_max_gen": 5,
    }


def test_new_steps_are_sized_for_their_unfrozen_variables():
    assert StepSetup("s", "adsorption", {"is_kinetic": True}).optimizer["knobs"] == {
        "pop_size": 24, "n_max_gen": 12,
    }
    frozen = StepSetup("s", "bed", frozen=("bed_porosity",), optimizer=None)
    assert frozen.n_fitted_variables() == 1
    assert StepSetup("s", "tubing").n_fitted_variables() is None
    assert StepSetup("s", "tubing").optimizer["knobs"] == {"pop_size": 16, "n_max_gen": 12}
    explicit = default_optimizer("Nelder-Mead", maxiter=5)
    assert StepSetup("s", "bed", optimizer=explicit).optimizer == explicit


def test_estimated_simulations():
    assert estimated_simulations(default_optimizer(n_variables=2), 3) == 16 * 12 * 3
    assert estimated_simulations(default_optimizer("Nelder-Mead", maxiter=300), 2) == 600
    assert estimated_simulations(default_optimizer(), 2) is None


def test_current_best_average_reads_the_running_front():
    optimizer = SimpleNamespace(results=None)
    assert current_best_average(optimizer) is None

    front = SimpleNamespace(
        x_independent=np.array([[0.3, 1e-7], [0.4, 2e-7], [0.5, 3e-7]]),
        f=np.array([[0.01, 0.9], [0.2, 0.2], [0.9, 0.01]]),
    )
    optimizer.results = SimpleNamespace(pareto_fronts=[front], meta_front=front)
    candidate = current_best_average(optimizer)
    assert candidate == Candidate(index=1, x=(0.4, 2e-7), f=(0.2, 0.2), tags=(AVERAGE_TAG,))
