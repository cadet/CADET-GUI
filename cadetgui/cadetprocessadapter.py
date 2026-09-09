from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Sequence

from CADETProcess.modelBuilder import LWE, BatchElution
from CADETProcess.processModel import (
    BindingBaseClass,
    ChromatographicColumnBase,
    ComponentSystem,
    Cstr,
    GeneralRateModel,
    Langmuir,
    Linear,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    NoBinding,
    StericMassAction,
)

from .parameters import get_parameters as _param_metadata_for

Validator = Callable[[Any], None]
Transform = Callable[[Any], Any]


@dataclass(frozen=True)
class FieldSpec:
    """Describes one form field: its kind, default, bounds, and validation."""

    name: str
    kind: Literal["float", "float_list", "bool", "text"]
    label: str | None = None
    default: Any = None
    transform: Callable | None = None
    validate: Optional[Validator] = None
    min: float | None = None
    max: float | None = None
    units: str | None = None
    component_names: tuple[str, ...] | None = None


def require_positive(x: Any) -> None:
    """Raise ValueError unless x is a positive number."""
    if float(x) <= 0:
        raise ValueError("Must be > 0.")


def parse_float_list(v: Any) -> list[float]:
    """Parse a comma/semicolon/whitespace-separated string (or sequence) of floats."""
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    s = str(v)
    vals: list[float] = []
    for chunk in s.replace(";", ",").replace("\n", " ").split(","):
        for tok in chunk.split():
            if tok:
                vals.append(float(tok))
    return vals


# Units: mol/m^3_IV (inlet.rst CONST_COEFF), s (solver.rst SECTION_TIMES),
# flow_rate m^3/s by consistency with CADET-Core's other flow-rate fields.
#
# Concentration fields (c_feed, c_load, c_salt_low, c_salt_high, c_eluent)
# aren't here -- they're per-component (`Inlet.c`), built by
# `_concentration_field()` per model-spec call instead.
PARAMS: dict[str, FieldSpec] = {
    "flow_rate": FieldSpec(
        "flow_rate", "float", "Flow rate", 1.0e-6,
        validate=require_positive, units="m^3/s",
    ),
    "feed_duration": FieldSpec(
        "feed_duration", "float", "Feed duration", 60.0,
        validate=require_positive, units="s",
    ),
    "load_duration": FieldSpec(
        "load_duration", "float", "Load duration", 60.0,
        validate=require_positive, units="s",
    ),
    "cycle_time": FieldSpec(
        "cycle_time", "float", "Cycle time", 6000.0,
        validate=require_positive, units="s",
    ),
    "wash_duration": FieldSpec(
        "wash_duration", "float", "Wash duration", 10.0,
        validate=require_positive, units="s",
    ),
    "gradient_duration": FieldSpec(
        "gradient_duration", "float", "Gradient duration", 10.0,
        validate=require_positive, units="s",
    ),
    "final_wash_duration": FieldSpec(
        "final_wash_duration", "float", "Final wash duration", 10.0, units="s",
    ),
}


@dataclass
class ModelSpec:
    """A titled group of fields plus the build function that consumes their values."""

    title: str
    fields: list[FieldSpec] = field(default_factory=list)
    build: Callable[[Mapping[str, Any]], Any] | None = None


def _pick(keys: Sequence[str]) -> list[FieldSpec]:
    return [PARAMS[k] for k in keys]


def _concentration_field(
    name: str, label: str, default_scalar: float, column: ChromatographicColumnBase
) -> FieldSpec:
    """Per-component concentration field, sized/named from the column's ComponentSystem."""
    names = tuple(column.component_system.names)
    n_comp = len(names) or 1
    return FieldSpec(
        name, "float_list", label, [default_scalar] * n_comp,
        transform=parse_float_list, units="mol/m^3_IV", component_names=names,
    )


def batch_elution_spec(column: ChromatographicColumnBase) -> ModelSpec:
    """Build the Batch Elution model's ModelSpec for the given column."""

    def _build(v: Mapping[str, Any]) -> Any:
        return BatchElution(
            column=column,
            c_feed=v["c_feed"],
            flow_rate=float(v["flow_rate"]),
            feed_duration=float(v["feed_duration"]),
            cycle_time=float(v["cycle_time"]),
            c_eluent=v["c_eluent"],
        )

    fields = [
        _concentration_field("c_feed", "Feed concentration", 10.0, column),
        *_pick(["flow_rate", "feed_duration", "cycle_time"]),
        _concentration_field("c_eluent", "Eluent concentration", 0.0, column),
    ]
    return ModelSpec(title="Batch Elution", fields=fields, build=_build)


def lwe_spec(column: ChromatographicColumnBase) -> ModelSpec:
    """Build the Load-Wash-Elute model's ModelSpec for the given column."""

    def _build(v: Mapping[str, Any]) -> Any:
        return LWE(
            column=column,
            c_load=v["c_load"],
            c_salt_low=v["c_salt_low"],
            c_salt_high=v["c_salt_high"],
            flow_rate=float(v["flow_rate"]),
            load_duration=float(v["load_duration"]),
            wash_duration=float(v["wash_duration"]),
            gradient_duration=float(v["gradient_duration"]),
            final_wash_duration=float(v["final_wash_duration"]),
        )

    fields = [
        _concentration_field("c_load", "Load concentration", 50.0, column),
        _concentration_field("c_salt_low", "Low-salt buffer", 50.0, column),
        _concentration_field("c_salt_high", "High-salt buffer", 500.0, column),
        *_pick([
            "flow_rate", "load_duration", "wash_duration", "gradient_duration",
            "final_wash_duration",
        ]),
    ]
    return ModelSpec(title="Load–Wash–Elute (LWE)", fields=fields, build=_build)


# CLR/Flip-Flop/MRSSR: see ai-docs/REQUIREMENTS.md "Open decisions".
MODEL_REGISTRY: dict[str, Callable[[ChromatographicColumnBase], ModelSpec]] = {
    "Batch Elution": batch_elution_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
}

ColumnFactory = Callable[[ComponentSystem], ChromatographicColumnBase]


def make_grm(cs: ComponentSystem) -> ChromatographicColumnBase:
    """Build a General Rate Model column for the given component system."""
    col = GeneralRateModel(cs, name="GRM")
    return col


def make_lrmp(cs: ComponentSystem) -> ChromatographicColumnBase:
    """Build a Lumped Rate Model With Pores column for the given component system."""
    col = LumpedRateModelWithPores(cs, name="LRMP")
    return col


def make_lrm(cs: ComponentSystem) -> ChromatographicColumnBase:
    """Build a Lumped Rate Model Without Pores column for the given component system."""
    col = LumpedRateModelWithoutPores(cs, name="LRM")
    return col


def make_cstr(cs: ComponentSystem) -> ChromatographicColumnBase:
    """Build a CSTR column for the given component system."""
    col = Cstr(cs, name="CSTR")
    return col


# Dict keys double as the dropdown's option labels, written out in full.
DEFAULT_COLUMN_FACTORIES: Dict[str, ColumnFactory] = {
    "General Rate Model (GRM)": make_grm,
    "Lumped Rate Model With Pores (LRMP)": make_lrmp,
    "Lumped Rate Model Without Pores (LRM)": make_lrm,
    "Continuous Stirred Tank Reactor (CSTR)": make_cstr,
}

BindingFactory = Callable[[ComponentSystem], BindingBaseClass]


def make_no_binding(cs: ComponentSystem) -> BindingBaseClass:
    """Build a NoBinding model for the given component system."""
    return NoBinding(cs, name="NoBinding")


def make_linear_binding(cs: ComponentSystem) -> BindingBaseClass:
    """Build a Linear binding model for the given component system."""
    return Linear(cs, name="Linear")


def make_langmuir_binding(cs: ComponentSystem) -> BindingBaseClass:
    """Build a Langmuir binding model for the given component system."""
    return Langmuir(cs, name="Langmuir")


def make_sma_binding(cs: ComponentSystem) -> BindingBaseClass:
    """Build a Steric Mass Action binding model for the given component system."""
    return StericMassAction(cs, name="StericMassAction")


# "None" first so a ChoiceField over this dict defaults to it, matching
# CADET-Process's own default (an unconfigured column already has NoBinding).
DEFAULT_BINDING_FACTORIES: Dict[str, BindingFactory] = {
    "None": make_no_binding,
    "Linear": make_linear_binding,
    "Langmuir": make_langmuir_binding,
    "Steric Mass Action (SMA)": make_sma_binding,
}


def _unique_preserve_order(names: Sequence[str]) -> list[str]:
    """Return names in original order, dropping duplicates (first occurrence wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _infer_kind(x: Any) -> str:
    if isinstance(x, (list, tuple)):
        return "float_list"
    if isinstance(x, bool):
        return "bool"
    return "float"


# Starting values so a blank form doesn't Apply a degenerate column;
# CADET-Core has no canonical default for these. `None` model slot = shared
# across column models; add a specific model name only to override it.
_GUI_SEED_DEFAULTS: dict[tuple[str, Optional[str], str], float] = {
    ("column", None, "diameter"): 0.024,
    ("column", None, "length"): 0.5,
    ("column", None, "axial_dispersion"): 1e-8,
    ("column", None, "bed_porosity"): 0.72,
    ("column", None, "particle_porosity"): 0.6,
    ("column", None, "particle_radius"): 5.0e-6,
    ("column", None, "film_diffusion"): 1e-3,
    ("column", None, "pore_diffusion"): 1e-10,
}


def _seed_default(category: str, model_name: str, name: str) -> float:
    key = (category, model_name, name)
    if key in _GUI_SEED_DEFAULTS:
        return _GUI_SEED_DEFAULTS[key]
    return _GUI_SEED_DEFAULTS.get((category, None, name), 0.0)


# Per-component in CADET-Process but usually entered as one shared value,
# unlike binding parameters (per-component by physical necessity). Default
# scalar; `ConfigurationWidget`'s multiplex toggle opts a name into
# per-component editing -- CADET-Process broadcasts a scalar assignment to
# every component either way.
MULTIPLEXABLE_COLUMN_PARAMS = frozenset({"axial_dispersion", "film_diffusion", "pore_diffusion"})


def _category_and_model(obj: Any) -> tuple[Optional[str], str]:
    model_name = type(obj).__name__
    if isinstance(obj, BindingBaseClass):
        return "binding", model_name
    if isinstance(obj, ChromatographicColumnBase) or isinstance(obj, Cstr):
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
    """Resolve one parameter's kind/bounds/units/default.

    Ground truth comes from `parameters/interface.json` via
    `category`/`model_name` (nested per-model, since e.g. `Langmuir.capacity`
    and `StericMassAction.capacity` differ in shape despite the same name).
    Falls back to inferring from the object's current value for an
    unregistered category/model/parameter. `multiplex` overrides
    `component_dependent` for `MULTIPLEXABLE_COLUMN_PARAMS` only.
    """
    meta = None
    if category is not None:
        try:
            meta = _param_metadata_for(category, model_name).get(name)
        except KeyError:
            meta = None

    current = getattr(obj, name, None)

    if meta is None:
        kind = _infer_kind(current)
        transform = parse_float_list if kind == "float_list" else None
        return current, kind, transform, {}, None

    dtype = meta["dtype"]
    component_dependent = meta["component_dependent"]
    if multiplex is not None and name in MULTIPLEXABLE_COLUMN_PARAMS:
        component_dependent = bool(multiplex.get(name, False))
    kind = "float_list" if (dtype == "float" and component_dependent) else dtype

    if current is not None and isinstance(current, (list, tuple)) and kind == "float":
        # CADET-Process stores these as a list even after scalar broadcast.
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
    obj: Any, *, multiplex: Optional[Dict[str, bool]] = None
) -> ModelSpec:
    """Build a ModelSpec from any object exposing `required_parameters`.

    Generic over `obj` (column, binding model, ...) so the same function
    drives every form. `multiplex` only matters for
    `MULTIPLEXABLE_COLUMN_PARAMS`.
    """
    req = getattr(obj, "required_parameters", None) or []
    names = _unique_preserve_order(list(req))
    category, model_name = _category_and_model(obj)

    # is_kinetic isn't in CADET-Process's own required_parameters, but every
    # binding model with a real isotherm needs it settable. `names` is only
    # non-empty for those (NoBinding's required_parameters is []).
    if category == "binding" and names:
        names.append("is_kinetic")

    component_names = tuple(obj.component_system.names) if hasattr(obj, "component_system") else ()
    fields: list[FieldSpec] = []
    kinds: dict[str, str] = {}

    for name in names:
        default, kind, transform, bounds, units = _resolve_param(
            obj, category, model_name, name, multiplex=multiplex
        )
        kinds[name] = kind
        label = name.replace("_", " ").capitalize()
        fs_kwargs = dict(
            name=name, kind=kind, label=label, default=default, transform=transform, **bounds
        )
        if units is not None:
            fs_kwargs["units"] = units
        if kind == "float_list" and component_names:
            fs_kwargs["component_names"] = component_names
        fields.append(FieldSpec(**fs_kwargs))

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
