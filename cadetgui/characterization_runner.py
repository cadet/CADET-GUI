"""Run one characterization step over N comparisons and choose a posterior explicitly.

A step fits one `CADETProcess.characterization` stage with one objective per
comparison. `run` returns the whole final front; nothing is written to a
`ParameterStore` until `posterior` is called with a chosen `Candidate`.
Headless (no ipywidgets).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
from CADETProcess.optimization import OptimizationProblem

from .cadetprocessadapter import COLUMN_MODELS
from .characterization_stages import (
    VariableDef,
    build_problem,
    describe_stage,
    write_targets,
)
from .comparison import Comparison
from .optimizer_runner import OPTIMIZERS, _front, run_optimization
from .parameter_store import (
    ParameterStore,
    Provenance,
    Step,
    read_process,
    spec_for,
)
from .parameter_store import (
    missing_requirements as _missing_requirements,
)
from .process_builder import check_recipe
from .simulation import Simulator

__all__ = [
    "StepSetup",
    "default_optimizer",
    "default_optimizer_knobs",
    "fitted_variables",
    "estimated_simulations",
    "BuiltStep",
    "StepResult",
    "Candidate",
    "build",
    "species_gaps",
    "run",
    "pareto_candidates",
    "current_best_average",
    "posterior",
    "missing_requirements",
]

AVERAGE_TAG = "best average"
DEFAULT_OPTIMIZER = "U-NSGA-III"


def default_optimizer_knobs(optimizer_name: str, n_variables: int) -> dict[str, int]:
    """Return knob values sized for a step fitting `n_variables` variables.

    U-NSGA-III: `pop_size = max(16, 8 * n_variables)`, `n_max_gen = 12`. Nelder-Mead:
    `maxiter = 200 * n_variables`, bounded to 200-1000 since every iteration simulates
    each measurement. Optimizers without a rule get their `OPTIMIZERS` knob defaults.
    """
    n = max(int(n_variables), 1)
    if optimizer_name == "U-NSGA-III":
        return {"pop_size": max(16, 8 * n), "n_max_gen": 12}
    if optimizer_name == "Nelder-Mead":
        return {"maxiter": min(max(200 * n, 200), 1000)}
    return {knob.attr: knob.default for knob in OPTIMIZERS[optimizer_name].knobs}


def default_optimizer(
    name: str = DEFAULT_OPTIMIZER, n_variables: Optional[int] = None, **knobs: int
) -> dict:
    """Return `{"name": name, "knobs": {...}}`, `knobs` overriding the defaults.

    With `n_variables`, defaults come from `default_optimizer_knobs`; without, from the
    `OPTIMIZERS` knob defaults, where 0 lets CADET-Process size population and generations.
    """
    spec = OPTIMIZERS[name]
    defaults = {knob.attr: knob.default for knob in spec.knobs}
    unknown = set(knobs) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown {name} setting(s) {sorted(unknown)}.")
    if n_variables is not None:
        defaults.update(default_optimizer_knobs(name, n_variables))
    return {"name": name, "knobs": {**defaults, **{k: int(v) for k, v in knobs.items()}}}


def fitted_variables(variables: Sequence[VariableDef], frozen: Sequence[str] = ()) -> list[str]:
    """Return the names of the variables the optimizer searches: bounded and not frozen."""
    return [v.name for v in variables if v.lb is not None and v.name not in frozen]


def estimated_simulations(optimizer: Mapping[str, Any], n_comparisons: int) -> Optional[int]:
    """Return the approximate number of simulations a run costs.

    None when CADET-Process sizes the run (a U-NSGA-III knob of 0). U-NSGA-III:
    population x generations x measurements. Nelder-Mead: `maxiter` x measurements,
    approximate since scipy's evaluations per iteration vary.
    """
    knobs = optimizer["knobs"]
    if optimizer["name"] == "U-NSGA-III":
        if not knobs["pop_size"] or not knobs["n_max_gen"]:
            return None
        return knobs["pop_size"] * knobs["n_max_gen"] * n_comparisons
    if optimizer["name"] == "Nelder-Mead":
        return knobs["maxiter"] * n_comparisons
    return None


@dataclass
class StepSetup:
    """One step: a stage, its options, the comparisons it fits jointly, bounds, frozen names.

    `optimizer` is `{"name": <OPTIMIZERS key>, "knobs": {attr: int}}` (see `default_optimizer`);
    left as None, it becomes the default optimizer sized for the fitted variables
    (the smallest size while the options are invalid). `excluded` names the measurements
    of the step's experiment types left out of the fit; None means not recorded.
    """

    name: str
    stage: str
    options: dict = field(default_factory=dict)
    comparisons: list[Comparison] = field(default_factory=list)
    bounds: dict = field(default_factory=dict)
    frozen: Sequence[str] = ()
    requires: Sequence[str] = ()
    optimizer: Optional[dict] = None
    excluded: Optional[Sequence[str]] = None

    def __post_init__(self) -> None:
        """Size the default optimizer when none is given."""
        if self.optimizer is None:
            self.optimizer = default_optimizer(n_variables=self.n_fitted_variables() or 0)

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], comparisons: Mapping[str, Comparison]
    ) -> "StepSetup":
        """Build from a manifest step entry; `comparisons` resolves its comparison names."""
        return cls(
            name=raw["name"],
            stage=raw["stage"],
            options=dict(raw.get("options") or {}),
            comparisons=[comparisons[name] for name in raw["comparisons"]],
            bounds={k: tuple(v) for k, v in (raw.get("bounds") or {}).items()},
            frozen=tuple(raw.get("frozen") or ()),
            requires=tuple(raw.get("requires") or ()),
            optimizer=_optimizer_from_dict(raw.get("optimizer")),
            excluded=tuple(raw["excluded"]) if "excluded" in raw else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest step entry; comparisons are referenced by name."""
        raw = {
            "name": self.name,
            "stage": self.stage,
            "options": dict(self.options),
            "comparisons": [c.name for c in self.comparisons],
            "bounds": {k: list(v) for k, v in self.bounds.items()},
            "frozen": list(self.frozen),
            "requires": list(self.requires),
            "optimizer": {"name": self.optimizer["name"], "knobs": dict(self.optimizer["knobs"])},
        }
        if self.excluded is not None:
            raw["excluded"] = list(self.excluded)
        return raw

    @property
    def provides(self) -> list[str]:
        """Parameter paths this step writes: the stage's write targets minus frozen ones."""
        targets = write_targets(describe_stage(self.stage, **self.options))
        return [path for name, path in targets.items() if name not in self.frozen]

    @property
    def step(self) -> Step:
        """The setup as a `parameter_store.Step`, for chain checks."""
        return Step(name=self.name, requires=tuple(self.requires), provides=tuple(self.provides))

    def n_fitted_variables(self) -> Optional[int]:
        """Return how many variables the optimizer searches; None while the options are invalid."""
        try:
            variables = describe_stage(self.stage, **self.options)
        except ValueError:
            return None
        return len(fitted_variables(variables, self.frozen))

    @property
    def objective_names(self) -> list[str]:
        """One objective per comparison, in order."""
        return [c.name for c in self.comparisons]


def _optimizer_from_dict(raw: Optional[Mapping[str, Any]]) -> Optional[dict]:
    if not raw:
        return None
    return default_optimizer(raw["name"], **dict(raw.get("knobs") or {}))


@dataclass(frozen=True)
class BuiltStep:
    """The characterization problem and the processes it writes into (one per comparison)."""

    problem: OptimizationProblem
    processes: list


@dataclass(frozen=True)
class StepResult:
    """The final front of one step run.

    `x` rows are parallel to `variable_names` (the problem's independent variables),
    `f` rows to `objective_names`. After a cancel, `x`/`f` hold the last full front.
    """

    step: str
    variable_names: list[str]
    objective_names: list[str]
    x: np.ndarray
    f: np.ndarray
    success: bool
    message: str
    cancelled: bool
    optimizer_name: str
    built: BuiltStep


@dataclass(frozen=True)
class Candidate:
    """One front member offered for posterior selection, with the criteria it wins."""

    index: int
    x: tuple[float, ...]
    f: tuple[float, ...]
    tags: tuple[str, ...]


def missing_requirements(setup: StepSetup, store: ParameterStore) -> list[str]:
    """Return `setup.requires` paths `store` does not hold, without raising."""
    return _missing_requirements(setup.step, store)


def species_gaps(setup: StepSetup, store: ParameterStore) -> dict[str, list[str]]:
    """Return `{path: missing species}` for stored species-indexed values the step can't apply.

    A path is listed when a comparison's process carries it but the store holds no value
    for some of that process's species, e.g. a periphery dispersion probed with another
    tracer. `parameter_store.transfer_species` closes such a gap explicitly.
    """
    gaps: dict[str, list[str]] = {}
    for comparison in setup.comparisons:
        check = check_recipe(comparison.recipe, comparison.overrides)
        if check.error is not None:
            raise ValueError(f"Comparison {comparison.name!r}: {check.error}")
        for path, entry in store.entries.items():
            if not store.spec(path).species_indexed or not check.has_parameter(path):
                continue
            for name in check.species:
                if name not in entry.value and name not in gaps.setdefault(path, []):
                    gaps[path].append(name)
    return {path: names for path, names in gaps.items() if names}


def build(setup: StepSetup, store: ParameterStore) -> BuiltStep:
    """Build one process + comparator per comparison and the stage's problem over them."""
    names = setup.objective_names
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Step {setup.name!r}: duplicate measurement names {duplicates}.")
    if not names:
        raise ValueError(f"Step {setup.name!r} has no measurements.")

    processes, comparators = [], []
    for comparison in setup.comparisons:
        process, comparator = comparison.build(store)
        processes.append(process)
        comparators.append(comparator)

    problem = build_problem(
        setup.stage, processes, comparators, Simulator(),
        options=setup.options, bounds=setup.bounds, frozen=setup.frozen,
    )
    return BuiltStep(problem=problem, processes=processes)


def _start_point(problem: OptimizationProblem) -> list[float]:
    """Return the independent variables' current process values, clipped into bounds."""
    lower = problem.lower_bounds_independent
    upper = problem.upper_bounds_independent
    x0 = []
    for name, lb, ub in zip(problem.independent_variable_names, lower, upper):
        value = problem.get_variable_value(name)
        if value is None or not np.isfinite(np.ravel(value)[0]):
            value = (lb + ub) / 2.0
        x0.append(float(np.clip(np.ravel(value)[0], lb, ub)))
    return x0


def run(
    setup: StepSetup,
    store: ParameterStore,
    optimizer_name: Optional[str] = None,
    optimizer_kwargs: Optional[Mapping[str, int]] = None,
    cancel_event: Optional[threading.Event] = None,
    on_optimizer_ready: Optional[Callable[[Any], None]] = None,
    built: Optional[BuiltStep] = None,
) -> StepResult:
    """Fit `setup` starting from `store` and return the whole final front.

    `built` reuses an already built problem (e.g. one whose discretization the caller
    adjusted); by default the step is built from `store`. Without `optimizer_name`,
    `setup.optimizer` names the optimizer and supplies knobs `optimizer_kwargs` doesn't set.
    """
    if optimizer_name is None:
        optimizer_name = setup.optimizer["name"]
        optimizer_kwargs = {**setup.optimizer["knobs"], **(optimizer_kwargs or {})}
    built = built or build(setup, store)
    problem = built.problem
    outcome = run_optimization(
        problem, optimizer_name, optimizer_kwargs or {}, _start_point(problem),
        cancel_event=cancel_event, on_optimizer_ready=on_optimizer_ready,
    )
    n_var = len(problem.independent_variable_names)
    n_obj = len(setup.comparisons)
    return StepResult(
        step=setup.name,
        variable_names=list(problem.independent_variable_names),
        objective_names=setup.objective_names,
        x=np.array(outcome.front_x, dtype=float).reshape(-1, n_var),
        f=np.array(outcome.front_f, dtype=float).reshape(-1, n_obj),
        success=outcome.success,
        message=outcome.message,
        cancelled=outcome.cancelled,
        optimizer_name=optimizer_name,
        built=built,
    )


def pareto_candidates(result: StepResult) -> list[Candidate]:
    """Return the equal-weight-average winner and each objective's winner, merged by x."""
    if len(result.f) == 0:
        return []
    picks = [(AVERAGE_TAG, int(np.argmin(result.f.mean(axis=1))))]
    picks += [
        (f"best {name}", int(np.argmin(result.f[:, i])))
        for i, name in enumerate(result.objective_names)
    ]

    merged: dict[tuple[float, ...], Candidate] = {}
    for tag, index in picks:
        x = tuple(float(v) for v in result.x[index])
        if x in merged:
            merged[x] = replace(merged[x], tags=(*merged[x].tags, tag))
        else:
            f = tuple(float(v) for v in result.f[index])
            merged[x] = Candidate(index=index, x=x, f=f, tags=(tag,))
    return list(merged.values())


def current_best_average(optimizer: Any) -> Optional[Candidate]:
    """Return the equal-weight-average winner of a running optimizer's current front.

    Reads `optimizer.results` only; None before the first generation has finished.
    """
    front_x, front_f = _front(optimizer)
    if not front_x:
        return None
    index = int(np.argmin(np.asarray(front_f, dtype=float).mean(axis=1)))
    return Candidate(index=index, x=front_x[index], f=front_f[index], tags=(AVERAGE_TAG,))


def _probes(setup: StepSetup) -> list[str]:
    return list(dict.fromkeys(c.probe for c in setup.comparisons if c.probe))


def posterior(
    setup: StepSetup, built: BuiltStep, store: ParameterStore, candidate: Candidate
) -> ParameterStore:
    """Write `candidate` into the processes and return `store` updated with the fitted values.

    Species-indexed values are restricted to the comparisons' probe species when any
    probe names a species, each read from a process that carries it; otherwise every
    species of the first process is written.
    """
    built.problem.set_variables(list(candidate.x))
    process = built.processes[0]
    paths = setup.provides

    new_specs = {path: spec_for(process, path) for path in paths if path not in store.specs}
    reader = replace(store, specs={**store.specs, **new_specs})
    values = read_process(process, paths, reader)

    probes = _probes(setup)
    if any(s in p.component_system.species for p in built.processes for s in probes):
        for path in values:
            if not reader.spec(path).species_indexed:
                continue
            merged = {}
            for other in built.processes:
                present = [s for s in probes if s in other.component_system.species]
                if present:
                    read = read_process(other, [path], reader)[path]
                    merged.update({s: read[s] for s in present if s not in merged})
            values[path] = merged
    values = {
        path: {s: np.asarray(v).tolist() for s, v in value.items()}
        if isinstance(value, dict) else np.asarray(value).tolist()
        for path, value in values.items()
    }

    recipe = setup.comparisons[0].recipe
    column_bypassed = recipe.instrument is not None and "column" in recipe.instrument.bypass_units
    column = None if column_bypassed else COLUMN_MODELS.get(recipe.column_key)
    provenance = Provenance(
        step=setup.name,
        probe=", ".join(probes) or None,
        source=", ".join(setup.objective_names),
        model=column.__name__ if column is not None else None,
        metric={
            f"{c.name}_{c.metric}": float(value)
            for c, value in zip(setup.comparisons, candidate.f)
        },
    )
    return store.updated(values, provenance, specs=new_specs)
