"""Parameter metadata: unit/description/shape/bounds/co_name/default/required-ness,
all introspected live off real CADET-Process descriptors and objects. Nothing here
is hand-typed against a separate copy of CADET-Process's own knowledge.

CADET-Process's own `ParameterBase` accepts `unit=`/`description=` kwargs, and (as of
https://github.com/fau-advanced-separations/CADET-Process/pull/435) the column/
binding/solver descriptors this module reads now actually set them, sourced from
CADET-Core's own interface docs. `component_dependent`/`dtype`/`min`/`max`/`co_name`/
`default` are read live off the actual descriptor class (`Sized`/`Ranged`/`Switch`/
`Bool`/`Integer` from `CADETProcess.dataStructure`) and off
`CADETProcess.simulator.cadetAdapter`'s own `unit_parameters_map`/
`adsorption_parameters_map` -- the literal mapping CADET-Process uses to serialize to
CADET-Core, so `co_name` can't disagree with what's actually written. None of this can
drift from CADET-Process the way a hand-typed copy could, because it *is*
CADET-Process.

A parameter's *name* itself is also read live, off `cls._parameters` -- CADET-Process's
own class-level list of every parameter it exposes (built by the same metaclass as
`cls._required_parameters`, so -- like that one -- its *order* is hash-seed-random
across process runs, not a stable fact; only the *set* is). This module returns names
in plain alphabetical order instead of a curated one.

`required_parameters()` is live too, but *not* off the class-level
`cls._required_parameters` CADET-Process's metaclass builds -- that's a
superset (e.g. `Cstr._required_parameters` includes `flow_rate`, but a
constructed `Cstr(...).required_parameters` doesn't: confirmed directly,
CADET-Process does extra instance-level filtering the class attribute never
captures). Only a real, minimally-built instance is authoritative, so that's
what `_required_parameters_live` constructs.

The one thing live introspection can't reach: `co_group`, the CADET-Python H5
wrapper tree path for a solver-category model (e.g. `/solver/time_integrator`)
-- CADETProcess.simulator.cadetAdapter writes it as a plain uppercase HDF5
group, not through a cp_name<->co_name map the way column/binding parameters
are, so it isn't stored as an introspectable string anywhere in CADET-Process.
That one stays a hand-typed constant, in `_SOLVER_CO_GROUPS` below.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from CADETProcess.dataStructure import Bool, Integer, Ranged, Sized, Switch
from CADETProcess.processModel import (
    ComponentSystem,
    Cstr,
    GeneralRateModel,
    Langmuir,
    Linear,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    NoBinding,
    StericMassAction,
    TubularReactor,
)
from CADETProcess.simulator.cadetAdapter import (
    SolverTimeIntegratorParameters,
    adsorption_parameters_map,
    unit_parameters_map,
)

__all__ = [
    "get_parameters",
    "get_parameter",
    "required_parameters",
    "get_co_group",
]

# The real CADET-Process class behind each (category, model name) this module
# knows about -- what live introspection actually reads. Kept in sync with
# test_every_registered_parameter_resolves_a_real_live_descriptor.
_MODEL_CLASSES: dict[tuple[str, str], type] = {
    ("column", "GeneralRateModel"): GeneralRateModel,
    ("column", "LumpedRateModelWithPores"): LumpedRateModelWithPores,
    ("column", "LumpedRateModelWithoutPores"): LumpedRateModelWithoutPores,
    ("column", "TubularReactor"): TubularReactor,
    ("column", "Cstr"): Cstr,
    ("binding", "NoBinding"): NoBinding,
    ("binding", "Linear"): Linear,
    ("binding", "Langmuir"): Langmuir,
    ("binding", "StericMassAction"): StericMassAction,
    ("solver", "SolverTimeIntegratorParameters"): SolverTimeIntegratorParameters,
}

# CADET-Process's own cp_name<->co_name maps, keyed the same way as _MODEL_CLASSES'
# category. No such map exists for "solver" (it writes a plain-uppercase group,
# not one of these two conversion tables) -- co_name stays None there.
_CO_NAME_MAPS = {"column": unit_parameters_map, "binding": adsorption_parameters_map}

# See module docstring: the one piece of metadata live introspection can't reach.
_SOLVER_CO_GROUPS: dict[str, str] = {
    "SolverTimeIntegratorParameters": "/solver/time_integrator",
}


def get_co_group(model: str) -> str | None:
    """CADET-Core H5 group path for a solver-category model, e.g.
    `get_co_group("SolverTimeIntegratorParameters") == "/solver/time_integrator"`.
    `None` for anything not registered."""
    return _SOLVER_CO_GROUPS.get(model)


@lru_cache(maxsize=1)
def _inverse_co_name_maps() -> dict[tuple[str, str], dict[str, str]]:
    """`(category, model_name) -> {cp_name: co_name}`, inverted from CADET-Process's
    own parameter maps (see module docstring)."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    for category, param_map in _CO_NAME_MAPS.items():
        for model_name, entry in param_map.items():
            out[(category, model_name)] = {
                cp_name: co_name for co_name, cp_name in entry["parameters"].items()
            }
    return out


def _descriptor(cls: type, name: str) -> Any | None:
    """The real `ParameterBase` descriptor backing `name` on `cls`, or `None`.

    A few attributes (`q`, `cp`, `surface_diffusion`) are plain Python
    `@property` wrappers around a differently-sized private descriptor
    (`_q`/`_cp`/`_surface_diffusion`, e.g. sized by `n_bound_states` rather
    than `n_comp`) -- confirmed directly against the installed CADET-Process,
    not assumed. Falls back to that convention when `name` itself resolves to
    a plain `property` rather than a descriptor.
    """
    desc = getattr(cls, name, None)
    if isinstance(desc, property):
        desc = getattr(cls, f"_{name}", None)
    return desc if hasattr(desc, "default") else None


def _live_metadata(category: str, model_name: str, name: str) -> dict[str, Any] | None:
    """Full metadata for one parameter, introspected off the real CADET-Process
    descriptor. `None` if `(category, model_name)` isn't registered in
    `_MODEL_CLASSES` or the attribute can't be resolved to a real descriptor
    (see `_descriptor`)."""
    cls = _MODEL_CLASSES.get((category, model_name))
    if cls is None:
        return None
    descriptor = _descriptor(cls, name)
    if descriptor is None:
        return None

    if isinstance(descriptor, Bool):
        dtype = "bool"
    elif isinstance(descriptor, Integer):
        dtype = "int"
    else:
        dtype = "float"

    live: dict[str, Any] = {
        "component_dependent": isinstance(descriptor, Sized),
        "dtype": dtype,
        "co_name": _inverse_co_name_maps().get((category, model_name), {}).get(name),
        "unit": descriptor.unit,
        "description": descriptor.description,
    }
    if descriptor.default is not None:
        live["default"] = descriptor.default

    if isinstance(descriptor, Ranged):
        if math.isfinite(descriptor.lb):
            live["min"] = float(descriptor.lb)
        if math.isfinite(descriptor.ub):
            live["max"] = float(descriptor.ub)
    elif isinstance(descriptor, Switch):
        # e.g. TubularReactorBase.flow_direction = Switch(valid=[-1, 1]) --
        # not a Ranged constraint, but still a numeric range worth rendering
        # as bounds.
        valid = [v for v in descriptor.valid if isinstance(v, (int, float))]
        if valid:
            live["min"], live["max"] = float(min(valid)), float(max(valid))

    return live


def get_parameters(category: str, model: str) -> dict[str, dict]:
    """All known parameters for `model` in `category`, keyed by CADET-Process name,
    in alphabetical order.

    Names come from `cls._parameters` (see module docstring for why only its
    *set*, not its order, is trustworthy), filtered to the ones that actually
    resolve to a real descriptor (see `_descriptor`). Each entry's metadata is
    entirely live (see `_live_metadata`).

    Raises `KeyError` if `(category, model)` isn't registered in
    `_MODEL_CLASSES`.
    """
    cls = _MODEL_CLASSES[(category, model)]
    names = {name for name in cls._parameters if _descriptor(cls, name) is not None}
    return {name: _live_metadata(category, model, name) for name in sorted(names)}


def get_parameter(category: str, model: str, name: str) -> dict:
    """Metadata for one parameter, e.g. `get_parameter("binding", "Langmuir", "capacity")`."""
    return get_parameters(category, model)[name]


@lru_cache(maxsize=None)
def _required_parameters_live(category: str, model: str) -> frozenset[str]:
    """The real required-parameter set for a fresh, minimally-built `model`
    instance -- see the module docstring for why this must be a real instance,
    not `cls._required_parameters`. Cached: the underlying CADET-Process
    objects only need constructing once per (category, model)."""
    cls = _MODEL_CLASSES.get((category, model))
    if cls is None:
        return frozenset()
    obj = cls() if category == "solver" else cls(ComponentSystem(1), name="x")
    return frozenset(obj.required_parameters)


def required_parameters(category: str, model: str) -> list[str]:
    """Return the subset of `get_parameters(...)` CADET-Process requires to
    build `model`, in alphabetical order (CADET-Process's own order is
    hash-seed-random across process runs, not a stable fact to return -- see
    `ai-docs/UPSTREAM_ISSUES.md` #4)."""
    required = _required_parameters_live(category, model)
    return [name for name in get_parameters(category, model) if name in required]
