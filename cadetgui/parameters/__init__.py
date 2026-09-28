"""Parameter metadata (unit, description, shape, bounds, dtype, CADET-Core name, default).

Everything is read live off the real CADET-Process descriptors and its own
CADET-Core name maps, so nothing is hand-typed against a copy of CADET-Process.
Parameter names come from `cls._parameters`, whose order is hash-seed-random
across runs, so they are returned alphabetically.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from CADETProcess.dataStructure import Bool, Integer, Ranged, Sized, Switch
from CADETProcess.processModel import (
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

__all__ = ["get_parameters", "get_parameter"]

# The CADET-Process class behind each (category, model name).
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

# CADET-Process's cp_name<->co_name maps; "solver" has none, so its co_name is None.
_CO_NAME_MAPS = {"column": unit_parameters_map, "binding": adsorption_parameters_map}


@lru_cache(maxsize=1)
def _inverse_co_name_maps() -> dict[tuple[str, str], dict[str, str]]:
    """Return `{(category, model): {cp_name: co_name}}`, inverted from CADET-Process's maps."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    for category, param_map in _CO_NAME_MAPS.items():
        for model_name, entry in param_map.items():
            out[(category, model_name)] = {
                cp_name: co_name for co_name, cp_name in entry["parameters"].items()
            }
    return out


def _descriptor(cls: type, name: str) -> Any | None:
    """Return the `ParameterBase` descriptor backing `name` on `cls`, or `None`.

    `q`, `cp` and `surface_diffusion` are properties over a private descriptor
    (`_q`, ...) of a different size, so fall back to that.
    """
    desc = getattr(cls, name, None)
    if isinstance(desc, property):
        desc = getattr(cls, f"_{name}", None)
    return desc if hasattr(desc, "default") else None


def _live_metadata(category: str, model_name: str, name: str, descriptor: Any) -> dict[str, Any]:
    """Return one parameter's metadata, read off its CADET-Process descriptor."""
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
        # e.g. `flow_direction` is a Switch over [-1, 1]; expose it as bounds.
        valid = [v for v in descriptor.valid if isinstance(v, (int, float))]
        if valid:
            live["min"], live["max"] = float(min(valid)), float(max(valid))

    return live


def get_parameters(category: str, model: str) -> dict[str, dict]:
    """Return every parameter of `model` in `category` with its metadata, alphabetically.

    Raises `KeyError` for an unregistered `(category, model)`.
    """
    cls = _MODEL_CLASSES[(category, model)]
    descriptors = {name: _descriptor(cls, name) for name in sorted(set(cls._parameters))}
    return {
        name: _live_metadata(category, model, name, descriptor)
        for name, descriptor in descriptors.items()
        if descriptor is not None
    }


def get_parameter(category: str, model: str, name: str) -> dict:
    """Metadata for one parameter, e.g. `get_parameter("binding", "Langmuir", "capacity")`."""
    return get_parameters(category, model)[name]
