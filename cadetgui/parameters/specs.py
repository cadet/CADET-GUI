"""Form field specs, and specs read off any CADET-Process object's parameters."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Sequence

from CADETProcess.processModel import (
    BindingBaseClass,
    Cstr,
    TubularReactorBase,
)

from .metadata import get_parameters as _param_metadata_for

Validator = Callable[[Any], None]
Transform = Callable[[Any], Any]


@dataclass(frozen=True)
class FieldSpec:
    """Describes one form field: its kind, default, bounds, and validation."""

    name: str
    kind: Literal["float", "float_list", "bool", "text", "choice"]
    label: str | None = None
    default: Any = None
    transform: Transform | None = None
    validate: Optional[Validator] = None
    min: float | None = None
    max: float | None = None
    units: str | None = None
    component_names: tuple[str, ...] | None = None
    # "choice" only: (label, value) dropdown options.
    options: tuple[tuple[str, Any], ...] | None = None


def require_positive(x: Any) -> None:
    """Raise ValueError unless x is a positive number."""
    if float(x) <= 0:
        raise ValueError("Must be > 0.")


def require_finite_above(minimum: float = 0.0, *, inclusive: bool = False) -> Validator:
    """Return a validator rejecting NaN, inf and values below `minimum` (or at it, if exclusive)."""

    def _validate(x: Any) -> None:
        value = float(x)
        if not math.isfinite(value):
            raise ValueError("Must be a finite number.")
        if value < minimum or (value == minimum and not inclusive):
            comparison = ">=" if inclusive else ">"
            raise ValueError(f"Must be {comparison} {minimum:g}.")

    return _validate


def parse_float_list(v: Any) -> list[float]:
    """Parse a comma/semicolon/whitespace-separated string (or sequence) of floats."""
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    return [float(tok) for tok in re.split(r"[,;\s]+", str(v).strip()) if tok]


@dataclass
class ModelSpec:
    """A titled group of fields plus the build function that consumes their values."""

    title: str
    fields: list[FieldSpec] = field(default_factory=list)
    build: Callable[[Mapping[str, Any]], Any] | None = None
    # Script lines for standalone templates that wire their own FlowSheet; None otherwise.
    export: Callable[[Mapping[str, Any]], list[str]] | None = None
    # Display names of the `PhasedProcess` phases, in order.
    phase_names: tuple[str, ...] = ()


def _infer_kind(x: Any) -> str:
    if isinstance(x, (list, tuple)):
        return "float_list"
    if isinstance(x, bool):
        return "bool"
    return "float"


# Starting values so a blank form doesn't apply a degenerate column. A `None` model slot
# is shared across column models; a model name overrides it.
_GUI_SEED_DEFAULTS: dict[tuple[str, Optional[str], str], float] = {
    ("column", None, "diameter"): 0.005,
    ("column", None, "length"): 0.05,
    ("column", None, "axial_dispersion"): 1e-8,
    ("column", None, "bed_porosity"): 0.37,
    ("column", None, "total_porosity"): 0.75,
    ("column", None, "particle_porosity"): 0.6,
    ("column", None, "particle_radius"): 5.0e-6,
    ("column", None, "film_diffusion"): 1e-3,
    ("column", None, "pore_diffusion"): 1e-10,
    ("column", "Cstr", "init_liquid_volume"): 1e-6,
}


def _seed_default(category: str, model_name: str, name: str) -> float:
    key = (category, model_name, name)
    if key in _GUI_SEED_DEFAULTS:
        return _GUI_SEED_DEFAULTS[key]
    return _GUI_SEED_DEFAULTS.get((category, None, name), 0.0)


# Per-component in CADET-Process but usually entered as one shared value; the multiplex
# toggle opts a name into per-component editing.
MULTIPLEXABLE_COLUMN_PARAMS = frozenset({"axial_dispersion", "film_diffusion", "pore_diffusion"})

# Component-dependent in CADET-Process, but tubing/mixer segments get no multiplex toggle,
# so it always renders as a scalar.
_FORCE_SCALAR = frozenset({("TubularReactor", "axial_dispersion")})


def _category_and_model(obj: Any) -> tuple[Optional[str], str]:
    model_name = type(obj).__name__
    if isinstance(obj, BindingBaseClass):
        return "binding", model_name
    # Covers real columns and the tubing/mixer `TubularReactor` segments.
    if isinstance(obj, (TubularReactorBase, Cstr)):
        return "column", model_name
    return None, model_name


def _resolve_param(
    obj: Any,
    category: Optional[str],
    model_name: str,
    name: str,
    *,
    multiplex: Optional[Dict[str, bool]] = None,
) -> tuple[Any, str, Optional[Transform], dict[str, float], Optional[str]]:
    """Return `(default, kind, transform, bounds, units)` for one parameter.

    Metadata comes from `parameters.get_parameters()`; an unregistered parameter falls
    back to the kind of its current value. `multiplex` overrides `component_dependent`
    for `MULTIPLEXABLE_COLUMN_PARAMS`, and `_FORCE_SCALAR` overrides it always.
    """
    meta = None
    if category is not None:
        try:
            meta = _param_metadata_for(category, model_name).get(name)
        except KeyError:
            meta = None

    current = getattr(obj, name, None)

    if meta is None or meta.get("dtype") is None or meta.get("component_dependent") is None:
        kind = _infer_kind(current)
        transform = parse_float_list if kind == "float_list" else None
        return current, kind, transform, {}, None if meta is None else meta.get("unit")

    dtype = meta["dtype"]
    component_dependent = meta["component_dependent"]
    if multiplex is not None and name in MULTIPLEXABLE_COLUMN_PARAMS:
        component_dependent = bool(multiplex.get(name, False))
    if (model_name, name) in _FORCE_SCALAR:
        component_dependent = False
    kind = "float_list" if (dtype == "float" and component_dependent) else dtype

    if current is not None and isinstance(current, (list, tuple)) and kind == "float":
        # CADET-Process keeps a list even after a scalar assignment.
        default = current[0] if len(current) else _seed_default(category, model_name, name)
    elif current is not None:
        default = current
    elif kind == "float_list":
        n_comp = getattr(obj, "n_comp", None) or 1
        default = [_seed_default(category, model_name, name)] * n_comp
    else:
        default = _seed_default(category, model_name, name)

    bounds = {k: meta[k] for k in ("min", "max") if meta.get(k) is not None}
    transform = parse_float_list if kind == "float_list" else None
    return default, kind, transform, bounds, meta.get("unit")


def _coerce_to_kind(kind: str, val: Any) -> Any:
    if kind == "float_list":
        return parse_float_list(val)
    if kind == "bool":
        return bool(val)
    return float(val)


def build_parameter_config_spec(
    obj: Any, *, multiplex: Optional[Dict[str, bool]] = None, include_optional: bool = False
) -> ModelSpec:
    """Build a ModelSpec from any object exposing `required_parameters` (column, binding, ...).

    `multiplex` applies to `MULTIPLEXABLE_COLUMN_PARAMS`. `include_optional` also renders
    every scalar/list parameter `obj` currently holds a value for.
    """
    # `required_parameters` order varies with the hash seed, so sort for a stable form.
    names = sorted(set(getattr(obj, "required_parameters", None) or []))
    category, model_name = _category_and_model(obj)

    # Every isotherm needs `is_kinetic` settable; NoBinding has no required parameters.
    if category == "binding" and names:
        names.append("is_kinetic")

    if include_optional:
        # `obj.parameters` is frozen at construction; read live values via getattr, and
        # skip structured (dict-valued) ones.
        optional_names = [
            p for p in getattr(obj, "parameters", {})
            if p not in names and isinstance(getattr(obj, p, None), (int, float, bool, list, tuple))
        ]
        names.extend(optional_names)

    component_names = tuple(obj.component_system.names) if hasattr(obj, "component_system") else ()
    fields: list[FieldSpec] = []
    kinds: dict[str, str] = {}

    for name in names:
        default, kind, transform, bounds, units = _resolve_param(
            obj, category, model_name, name, multiplex=multiplex
        )
        kinds[name] = kind
        per_component = component_names if kind == "float_list" and component_names else None
        fields.append(
            FieldSpec(
                name, kind, name.replace("_", " ").capitalize(), default,
                transform=transform, units=units, component_names=per_component, **bounds,
            )
        )

    def _apply(values: Mapping[str, Any]) -> Any:
        for name in names:
            if name not in values:
                continue
            coerced = _coerce_to_kind(kinds[name], values[name])
            setattr(obj, name, coerced)
        return obj

    return ModelSpec(
        title=f"Configure {obj.__class__.__name__}",
        fields=fields,
        build=_apply,
    )


def parameter_defaults(
    obj: Any, names: Sequence[str], *, multiplex: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """Return the defaults of `names` on a fresh instance of `obj`'s class.

    CADET-Process's own defaults, else the GUI seed defaults; names without either are
    left out.
    """
    fresh = type(obj)(obj.component_system, name=obj.name)
    category, model_name = _category_and_model(fresh)
    defaults = {
        name: _resolve_param(fresh, category, model_name, name, multiplex=multiplex)[0]
        for name in names
    }
    return {name: value for name, value in defaults.items() if value is not None}
