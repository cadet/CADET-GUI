"""
Headless registry over CADETProcess.characterization's Characterize* classes.

Stage identity, option parameters and variable schema are all derived from the
classes themselves (`inspect.signature` for constructor options, the private
`_default_variables()` for the variable list) rather than hand-listed, so the
registry tracks CADET-Process instead of duplicating it. No ipywidgets
dependency.

Private API relied on:
- `CharacterizeBase._default_variables()`: no public equivalent exists upstream.
- The `self._<option_name>` attribute convention every subclass's `__init__`
  follows for its own constructor options (e.g. `CharacterizeTubing._tubing`,
  `CharacterizeAdsorptionParameters._is_kinetic`): used to build a stage
  instance via `cls.__new__` without processes/comparators/a simulator, which
  `_default_variables()` needs no other instance state for.
- `OptimizationProblem.remove_variable` is not implemented upstream (raises
  `NotImplementedError`), so freezing a variable overrides
  `_default_variables()` in a subclass instead.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from CADETProcess.characterization import (
    CharacterizeAdsorptionParameters,
    CharacterizeBase,
    CharacterizeBed,
    CharacterizeCapacity,
    CharacterizeParticles,
    CharacterizePreInjection,
    CharacterizeTubing,
)
from CADETProcess.comparison import Comparator
from CADETProcess.instruments import LCProcess
from CADETProcess.simulator import SimulatorBase


@dataclass(frozen=True)
class StageDef:
    """One characterization stage: its label, solver class and constructor options."""

    id: str
    label: str
    characterize_cls: type[CharacterizeBase]
    options: Mapping[str, inspect.Parameter]


@dataclass(frozen=True)
class VariableDef:
    """One optimization variable, as `_default_variables()` describes it.

    `is_dependent` marks a variable with no direct process write of its own:
    either a free helper variable (`targets=None`, e.g. kinetic mode's
    `equilibrium_constant`) or one resolved from other variables via
    `add_variable_dependency` after construction (e.g. `adsorption_rate` in
    kinetic mode).
    """

    name: str
    parameter_path: Optional[str]
    lb: Optional[float]
    ub: Optional[float]
    transform: Optional[str]
    indices: Optional[Any]
    is_dependent: bool


_BASE_PARAMS = frozenset(inspect.signature(CharacterizeBase.__init__).parameters) - {"kwargs"}


def _discover_options(cls: type[CharacterizeBase]) -> dict[str, inspect.Parameter]:
    """Return `cls`'s own constructor keyword parameters, beyond `CharacterizeBase`'s."""
    sig = inspect.signature(cls.__init__)
    return {
        name: param for name, param in sig.parameters.items()
        if name not in _BASE_PARAMS and param.kind != inspect.Parameter.VAR_KEYWORD
    }


def _stage_def(stage_id: str, label: str, cls: type[CharacterizeBase]) -> StageDef:
    return StageDef(id=stage_id, label=label, characterize_cls=cls, options=_discover_options(cls))


STAGES: dict[str, StageDef] = {
    stage.id: stage for stage in (
        _stage_def("tubing", "Extra-column volume (tubing)", CharacterizeTubing),
        _stage_def(
            "pre_injection", "Extra-column volume (pre-injection tubing + mixer)",
            CharacterizePreInjection,
        ),
        _stage_def("bed", "Column bed (porosity & axial dispersion)", CharacterizeBed),
        _stage_def("particles", "Particle transport", CharacterizeParticles),
        _stage_def("capacity", "Binding capacity", CharacterizeCapacity),
        _stage_def("adsorption", "Binding (steric mass action)", CharacterizeAdsorptionParameters),
    )
}


def _resolve_options(stage: StageDef, options: Mapping[str, Any]) -> dict[str, Any]:
    """Fill `options` with each option's constructor default; validate names."""
    unknown = set(options) - set(stage.options)
    if unknown:
        raise ValueError(
            f"Unknown option(s) for step type {stage.label!r}: {sorted(unknown)}"
        )

    resolved = {}
    for name, param in stage.options.items():
        if name in options:
            resolved[name] = options[name]
        elif param.default is not inspect.Parameter.empty:
            resolved[name] = param.default
        else:
            raise ValueError(f"Step type {stage.label!r} needs the option {name!r}.")
    return resolved


def _to_variable_def(var: Mapping[str, Any]) -> VariableDef:
    is_dependent = var.get("targets", -1) is None or "lb" not in var
    return VariableDef(
        name=var["name"],
        parameter_path=var.get("parameter_path"),
        lb=var.get("lb"),
        ub=var.get("ub"),
        transform=var.get("transform"),
        indices=var.get("indices"),
        is_dependent=is_dependent,
    )


def describe_stage(stage_id: str, **options: Any) -> list[VariableDef]:
    """Return the variable schema `stage_id` would fit for the given options.

    Builds a bare stage instance (`cls.__new__` plus the `_<option_name>`
    attributes its `__init__` would set) and reads its `_default_variables()`
    -- no processes, comparators or simulator are needed for this.
    """
    stage = STAGES[stage_id]
    resolved = _resolve_options(stage, options)

    obj = stage.characterize_cls.__new__(stage.characterize_cls)
    for name, value in resolved.items():
        setattr(obj, f"_{name}", value)

    return [_to_variable_def(var) for var in obj._default_variables()]


def write_targets(variables: Sequence[VariableDef]) -> dict[str, str]:
    """Return `{variable name: parameter path}` for every variable with a path.

    Helper variables with no parameter path (kinetic mode's `equilibrium_constant`
    and `kinetic_constant`) are omitted.
    """
    return {v.name: v.parameter_path for v in variables if v.parameter_path is not None}


def build_problem(
    stage_id: str,
    processes: LCProcess | list[LCProcess],
    comparators: Comparator | list[Comparator],
    simulator: SimulatorBase,
    *,
    options: Optional[Mapping[str, Any]] = None,
    bounds: Optional[Mapping[str, tuple[float, float]]] = None,
    frozen: Optional[Sequence[str]] = None,
) -> CharacterizeBase:
    """Build the characterization problem for `stage_id`.

    `frozen` variable names are dropped from `_default_variables()` before
    construction, so the process keeps whatever value it already carries for
    that parameter; `OptimizationProblem.remove_variable` is not implemented
    upstream. Freezing a variable that a dependency chain references (e.g.
    `kinetic_constant` in kinetic adsorption mode) raises, same as passing an
    unknown variable name to `add_variable_dependency` would.

    The plot callback `CharacterizeBase` registers breaks under
    `optimize(save_results=False)`; cleared here rather than left for callers
    to remember.
    """
    stage = STAGES[stage_id]
    resolved_options = _resolve_options(stage, options or {})
    frozen_set = set(frozen or ())

    cls = stage.characterize_cls
    if frozen_set:
        class _Filtered(cls):
            def _default_variables(self) -> list[dict]:
                return [
                    var for var in super()._default_variables()
                    if var["name"] not in frozen_set
                ]
        _Filtered.__name__ = cls.__name__
        cls = _Filtered

    bound_overrides = {
        name: {"lb": lb, "ub": ub} for name, (lb, ub) in (bounds or {}).items()
    }

    problem = cls(
        stage_id, processes, comparators=comparators, simulator=simulator,
        **resolved_options, **bound_overrides,
    )
    problem.callbacks.clear()
    return problem
