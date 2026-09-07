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

FieldKind = str
Validator = Callable[[Any], None]
Transform = Callable[[Any], Any]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Literal["float", "float_list", "bool", "text"]
    label: str | None = None
    default: Any = None
    transform: Callable | None = None
    validate: Optional[Validator] = None
    min: float | None = None
    max: float | None = None
    units: str | None = None


def require_positive(x: Any) -> None:
    if float(x) <= 0:
        raise ValueError("Must be > 0.")


def parse_float_list(v: Any) -> list[float]:
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    s = str(v)
    vals: list[float] = []
    for chunk in s.replace(";", ",").replace("\n", " ").split(","):
        for tok in chunk.split():
            if tok:
                vals.append(float(tok))
    return vals


PARAMS: dict[str, FieldSpec] = {
    "c_feed": FieldSpec("c_feed", "float_list", "Feed concentration", [10.0], transform=parse_float_list),
    "c_load": FieldSpec("c_load", "float_list", "Load concentration", [50.0], transform=parse_float_list),
    "c_salt_low": FieldSpec("c_salt_low", "float_list", "Low-salt buffer", [50.0], transform=parse_float_list),
    "c_salt_high": FieldSpec("c_salt_high", "float_list", "High-salt buffer", [500.0], transform=parse_float_list),
    "flow_rate": FieldSpec("flow_rate", "float", "Flow rate", 1.0e-6, validate=require_positive),
    "feed_duration": FieldSpec("feed_duration", "float", "Feed duration", 60.0, validate=require_positive),
    "load_duration": FieldSpec("load_duration", "float", "Load duration", 60.0, validate=require_positive),
    "cycle_time": FieldSpec("cycle_time", "float", "Cycle time", 6000.0, validate=require_positive),
    "wash_duration": FieldSpec("wash_duration", "float", "Wash duration", 10.0, validate=require_positive),
    "gradient_duration": FieldSpec("gradient_duration", "float", "Gradient duration", 10.0, validate=require_positive),
    "final_wash_duration": FieldSpec("final_wash_duration", "float", "Final wash duration", 10.0),
    "c_eluent": FieldSpec("c_eluent", "float", "Eluent (scalar)", 0.0),
}


@dataclass
class ModelSpec:
    title: str
    fields: list[FieldSpec] = field(default_factory=list)
    build: Callable[[Mapping[str, Any]], Any] | None = None


def _pick(keys: Sequence[str]) -> list[FieldSpec]:
    return [PARAMS[k] for k in keys]


def batch_elution_spec(column: ChromatographicColumnBase) -> ModelSpec:
    def _build(v: Mapping[str, Any]) -> Any:
        return BatchElution(
            column=column,
            c_feed=v["c_feed"],
            flow_rate=float(v["flow_rate"]),
            feed_duration=float(v["feed_duration"]),
            cycle_time=float(v["cycle_time"]),
            c_eluent=float(v["c_eluent"]),
        )

    return ModelSpec(
        title="Batch Elution",
        fields=_pick(["c_feed", "flow_rate", "feed_duration", "cycle_time", "c_eluent"]),
        build=_build,
    )


def lwe_spec(column: ChromatographicColumnBase) -> ModelSpec:
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

    return ModelSpec(
        title="Load–Wash–Elute (LWE)",
        fields=_pick([
            "c_load", "c_salt_low", "c_salt_high",
            "flow_rate", "load_duration", "wash_duration",
            "gradient_duration", "final_wash_duration",
        ]),
        build=_build,
    )


# CLR, Flip-Flop, and MRSSR specs were removed for now (see ai-docs/REQUIREMENTS.md
# "Open decisions" — not rejected, just out of scope until picked back up).
MODEL_REGISTRY: dict[str, Callable[[ChromatographicColumnBase], ModelSpec]] = {
    "Batch Elution": batch_elution_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
}

ColumnFactory = Callable[[ComponentSystem], ChromatographicColumnBase]


def make_grm(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = GeneralRateModel(cs, name="GRM")
    return col


def make_lrmp(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = LumpedRateModelWithPores(cs, name="LRMP")
    return col


def make_lrm(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = LumpedRateModelWithoutPores(cs, name="LRM")
    return col


def make_cstr(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = Cstr(cs, name="CSTR")
    return col


# Register default factories here
DEFAULT_COLUMN_FACTORIES: Dict[str, ColumnFactory] = {
    "GRM": make_grm,
    "LRMP": make_lrmp,
    "LRM": make_lrm,
    "CSTR": make_cstr,

}

BindingFactory = Callable[[ComponentSystem], BindingBaseClass]


def make_no_binding(cs: ComponentSystem) -> BindingBaseClass:
    return NoBinding(cs, name="NoBinding")


def make_linear_binding(cs: ComponentSystem) -> BindingBaseClass:
    return Linear(cs, name="Linear")


def make_langmuir_binding(cs: ComponentSystem) -> BindingBaseClass:
    return Langmuir(cs, name="Langmuir")


def make_sma_binding(cs: ComponentSystem) -> BindingBaseClass:
    return StericMassAction(cs, name="StericMassAction")


# "None" first so a ChoiceField over this dict defaults to it, matching
# CADET-Process's own default (an unconfigured column already has NoBinding).
DEFAULT_BINDING_FACTORIES: Dict[str, BindingFactory] = {
    "None": make_no_binding,
    "Linear": make_linear_binding,
    "Langmuir": make_langmuir_binding,
    "Steric Mass Action (SMA)": make_sma_binding,
}

PARAM_TYPE_OVERRIDES: Dict[str, FieldKind] = {}


def _unique_preserve_order(names: Sequence[str]) -> list[str]:
    """Return names in original order, dropping duplicates (first occurrence wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


PARAM_SCHEMA: dict[str, dict] = {
    "diameter":          {"kind": "float", "default": 0.024, "min": 0.0, "units": "m"},
    "bed_porosity":      {"kind": "float", "default": 0.72, "min": 0.0, "max": 1.0},
    "length":            {"kind": "float", "default": 0.5, "min": 0.0, "units": "m"},
    "pore_diffusion":    {"kind": "float", "default": 1e-10, "min": 0.0, "units": "m^2/s"},
    "film_diffusion":    {"kind": "float", "default": 1e-3, "min": 0.0, "units": "m/s"},
    "particle_porosity": {"kind": "float", "default": 0.6, "min": 0.0, "max": 1.0},
    "particle_radius":   {"kind": "float", "default": 5.0e-6, "min": 0.0, "units": "m"},
    "axial_dispersion":  {"kind": "float", "default": 1e-8, "min": 0.0, "units": "m^2/s"},

    # Binding-model parameters. Bounds/units sourced from CADET-Core's binding
    # model docs (cadet.github.io/master/interface/binding/{linear,
    # multi_component_langmuir,steric_mass_action}.html), not invented — see
    # ai-docs/ARCHITECTURE.md's "no inventing bounds" rule.
    #
    # `adsorption_rate`'s unit differs by model (Langmuir: m^3/(mol*s); Linear
    # and SMA: m^3_MP/m^3_SP/s) — left unspecified since this schema is shared
    # across binding model types and picking one would be wrong for the others.
    # `desorption_rate` (1/s) and `capacity` (mol/m^3) are consistent across
    # every model that uses them, so those do get a unit.
    "adsorption_rate":       {"kind": "float", "min": 0.0},
    "desorption_rate":       {"kind": "float", "min": 0.0, "units": "1/s"},
    "capacity":              {"kind": "float", "min": 0.0, "units": "mol/m^3"},
    "characteristic_charge": {"kind": "float", "min": 0.0},
    "steric_factor":         {"kind": "float", "min": 0.0},
}


def _infer_kind(x) -> str:
    if isinstance(x, (list, tuple)): return "float_list"
    if isinstance(x, bool): return "bool"
    return "float"


def _resolve_param(name: str, column_value):
    meta = PARAM_SCHEMA.get(name, {})
    default = meta.get("default", column_value)
    kind = meta.get("kind", _infer_kind(default))
    transform = parse_float_list if kind == "float_list" else None
    bounds = {k: meta[k] for k in ("min", "max") if k in meta}
    units = meta.get("units")
    return default, kind, transform, bounds, units


def _coerce_to_kind(kind: str, val):
    if kind == "float_list":
        return parse_float_list(val)
    if kind == "bool":
        return bool(val)
    # default: float
    return float(val)


def build_parameter_config_spec(obj: Any) -> ModelSpec:
    """Build a ModelSpec from any object exposing `required_parameters`.

    Generic over what `obj` is — a column, a binding model, anything with the
    CADET-Process `required_parameters` convention — so the same function
    drives both the column form and the binding-model form.
    """
    req = getattr(obj, "required_parameters", None) or []
    names = _unique_preserve_order(list(req))
    fields: list[FieldSpec] = []

    for name in names:
        current_val = getattr(obj, name, None)
        default, kind, transform, bounds, units = _resolve_param(name, current_val)
        label = name.replace("_", " ").capitalize()
        fs_kwargs = dict(name=name, kind=kind, label=label, default=default, transform=transform, **bounds)
        if units is not None:
            fs_kwargs["units"] = units
        fields.append(FieldSpec(**fs_kwargs))

    def _apply(values: Mapping[str, Any]) -> Any:
        for name in names:
            if name not in values:
                continue
            try:
                # prefer schema kind; fall back to explicit overrides; else infer
                schema_kind = PARAM_SCHEMA.get(name, {}).get("kind")
                kind = schema_kind or PARAM_TYPE_OVERRIDES.get(name)  # keep if you still have it
                if kind is None:
                    # last-resort inference from current value
                    cur = getattr(obj, name, None)
                    kind = _infer_kind(cur)
                coerced = _coerce_to_kind(kind, values[name])
                setattr(obj, name, coerced)
            except Exception:
                # swallow and continue so one bad value doesn't block the rest
                continue
        return obj

    return ModelSpec(
        title=f"Configure {obj.__class__.__name__}",
        fields=fields,
        build=_apply,  # <- pass the function directly; it takes (values)
    )
