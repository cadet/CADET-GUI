"""Parameter metadata: `interface.json`'s curated units/descriptions merged with
shape/bounds/co_name/default/required-ness introspected live off real
CADET-Process descriptors and objects.

CADET-Process's own `ParameterBase` accepts `unit=`/`description=` kwargs, but
nothing in `CADETProcess.processModel` actually sets them on any column/binding
attribute (confirmed by grepping the installed package) -- CADET-Core's docs are
the only source for those two fields, so `interface.json` stays their ground
truth (plus each model's parameter *order*, which CADET-Process itself can't
give stably -- see `ai-docs/UPSTREAM_ISSUES.md` #4).

Everything else this file used to hand-type per parameter (`component_dependent`,
`dtype`, `min`/`max`, `co_name`, `default`) is read live off the actual
descriptor class (`Sized`/`Ranged`/`Switch`/`Bool`/`Integer` from
`CADETProcess.dataStructure`) and off `CADETProcess.simulator.cadetAdapter`'s own
`unit_parameters_map`/`adsorption_parameters_map` -- the literal mapping
CADET-Process uses to serialize to CADET-Core, so `co_name` can't disagree with
what's actually written. This can't drift from CADET-Process the way a hand-typed
copy could, because it *is* CADET-Process.

`required_parameters()` is live too, but *not* off the class-level
`cls._required_parameters` CADET-Process's metaclass builds -- that's a
superset (e.g. `Cstr._required_parameters` includes `flow_rate`, but a
constructed `Cstr(...).required_parameters` doesn't: confirmed directly,
CADET-Process does extra instance-level filtering the class attribute never
captures). Only a real, minimally-built instance is authoritative, so that's
what `_required_parameters_live` constructs.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
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

__all__ = ["load_schema", "get_parameters", "get_parameter", "required_parameters"]

_SCHEMA_PATH = Path(__file__).parent / "interface.json"

# The real CADET-Process class behind each (category, model name) this schema
# registers -- what live introspection actually reads. Kept in sync with
# interface.json's own "models" keys by test_every_registered_model_resolves_live.
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


def _resolve_refs(node: Any, root: dict) -> Any:
    """Recursively replace `{"$ref": "a.b.c"}` with the dotted-path value from `root`."""
    if isinstance(node, dict):
        if set(node.keys()) == {"$ref"}:
            target: Any = root
            for part in node["$ref"].split("."):
                target = target[part]
            return _resolve_refs(target, root)
        return {k: _resolve_refs(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, root) for v in node]
    return node


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Load and `$ref`-resolve `interface.json`. Cached -- the file doesn't change at runtime."""
    raw = json.loads(_SCHEMA_PATH.read_text())
    return _resolve_refs(raw, raw)


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
    """Shape/bounds/co_name for one parameter, introspected off the real
    CADET-Process descriptor. `None` if `(category, model_name)` isn't
    registered in `_MODEL_CLASSES` or the attribute can't be resolved to a
    real descriptor (see `_descriptor`)."""
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
        # as bounds (see interface.json's flow_direction note).
        valid = [v for v in descriptor.valid if isinstance(v, (int, float))]
        if valid:
            live["min"], live["max"] = float(min(valid)), float(max(valid))

    return live


def get_parameters(category: str, model: str) -> dict[str, dict]:
    """All known parameters for `model` in `category`, keyed by CADET-Process name.

    Merges the category's curated `shared_parameters` (e.g. `length`, `diameter`,
    `axial_dispersion` -- identical `unit`/`description` across every
    TubularReactorBase-derived column) underneath the model's own curated
    `own_parameters`, for models that opt in via `extends_shared_parameters: true`
    -- e.g. `Cstr` has a different base class and no column geometry, so it must
    not inherit them. Each entry's `unit`/`description`/`source` come from that
    curated data; `component_dependent`/`dtype`/`min`/`max`/`co_name` are
    introspected live (see `_live_metadata`) and override any same-named curated
    field, so a model not registered in `_MODEL_CLASSES` still degrades to
    whatever (if anything) the curated entry happens to carry.
    """
    schema = load_schema()["categories"][category]
    model_entry = schema["models"][model]
    extends_shared = model_entry.get("extends_shared_parameters")
    shared = schema.get("shared_parameters", {}) if extends_shared else {}
    curated = {**shared, **model_entry["own_parameters"]}

    merged: dict[str, dict] = {}
    for name, entry in curated.items():
        live = _live_metadata(category, model, name)
        merged[name] = {**entry, **live} if live is not None else dict(entry)
    return merged


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
    build `model`, in this schema's own curated order (CADET-Process's own
    order is hash-seed-random across process runs, not a stable fact to
    return -- see `ai-docs/UPSTREAM_ISSUES.md` #4)."""
    required = _required_parameters_live(category, model)
    return [name for name in get_parameters(category, model) if name in required]
