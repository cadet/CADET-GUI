from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, Optional, Dict, Literal

from CADETProcess.processModel import (
    ChromatographicColumnBase,
    ComponentSystem,
    GeneralRateModel,
    LumpedRateModelWithPores,
    LumpedRateModelWithoutPores,
    Cstr
)

from CADETProcess.modelBuilder import LWE, BatchElution, CLR, FlipFlop, MRSSR

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
    "load_duration": FieldSpec("load_duration", "float", "Load duration", 10.0, validate=require_positive),
    "cycle_time": FieldSpec("cycle_time", "float", "Cycle time", 6000.0, validate=require_positive),
    "wash_duration": FieldSpec("wash_duration", "float", "Wash duration", 10.0, validate=require_positive),
    "gradient_duration": FieldSpec("gradient_duration", "float", "Gradient duration", 10.0, validate=require_positive),
    "final_wash_duration": FieldSpec("final_wash_duration", "float", "Final wash duration", 10.0),
    "c_eluent": FieldSpec("c_eluent", "float", "Eluent (scalar)", 0.0),
    "recycle_on":   FieldSpec("recycle_on",   "float", "Recycle on (t)",  250.0,  validate=require_positive),
    "recycle_off":   FieldSpec("recycle_off",   "float", "Recycle off (t)",  300.0,  validate=require_positive),
    "pump_volume":   FieldSpec("pump_volume",   "float", "Pump volume",      1e-9,  validate=require_positive),
    "V_tank":   FieldSpec("V_tank",   "float", "Tank volume",      1e-6,  validate=require_positive),
    "delay_flip":       FieldSpec("delay_flip",       "float", "Delay flip (t)",       325.0,  validate=require_positive),
    "delay_injection":  FieldSpec("delay_injection",  "float", "Delay injection (t)",  190.0,  validate=require_positive),
    "c_tank_init":   FieldSpec("c_tank_init",   "float_list", "Initial tank c",transform=parse_float_list)


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
    
def clr_spec(column: ChromatographicColumnBase) -> ModelSpec:
    """Closed Loop Recycling (CLR) spec."""
    def _build(v: Mapping[str, Any]) -> Any:
        from CADETProcess.modelBuilder import CLR
        return CLR(
            column=column,
            c_feed=v["c_feed"],
            flow_rate=float(v["flow_rate"]),
            feed_duration=float(v["feed_duration"]),
            recycle_off=float(v["recycle_off"]),
            cycle_time=float(v["cycle_time"]),
            c_eluent=float(v["c_eluent"]),     
            pump_volume=float(v["pump_volume"]),
        )

    return ModelSpec(
        title="Closed Loop Recycling (CLR)",
        fields=_pick([
            "c_feed",
            "flow_rate",
            "feed_duration",
            "recycle_off",
            "cycle_time",
            "c_eluent",
            "pump_volume",
        ]),
        build=_build,
    )

def flipflop_spec(column: ChromatographicColumnBase) -> ModelSpec:
    """Flip-Flop spec."""
    def _build(v: Mapping[str, Any]) -> Any:
        from CADETProcess.modelBuilder import FlipFlop
        return FlipFlop(
            column=column,
            c_feed=v["c_feed"],
            flow_rate=float(v["flow_rate"]),
            feed_duration=float(v["feed_duration"]),
            delay_flip=float(v["delay_flip"]),
            delay_injection=float(v["delay_injection"]),
            c_eluent=float(v["c_eluent"]),     # keep scalar eluent for now
        )

    return ModelSpec(
        title="Flip-Flop",
        fields=_pick([
            "c_feed",
            "flow_rate",
            "feed_duration",
            "delay_flip",
            "delay_injection",
            "c_eluent",
        ]),
        build=_build,
    )
    
def mrssr_spec(column: ChromatographicColumnBase) -> ModelSpec:
    """Mixed-Recycle Steady-State Recycling (MRSSR) spec."""
    def _build(v: Mapping[str, Any]) -> Any:
        from CADETProcess.modelBuilder import MRSSR
        # c_tank_init may be None (means: use feed concentration)
        return MRSSR(
            column=column,
            c_feed=v["c_feed"],
            flow_rate=float(v["flow_rate"]),
            feed_duration=float(v["feed_duration"]),
            recycle_on=float(v["recycle_on"]),
            recycle_off=float(v["recycle_off"]),
            cycle_time=float(v["cycle_time"]),
            V_tank=float(v["V_tank"]),
            c_eluent=float(v["c_eluent"]),     
            c_tank_init=v["c_tank_init"],    
        )

    return ModelSpec(
        title="MRSSR",
        fields=_pick([
            "c_feed",
            "flow_rate",
            "feed_duration",
            "recycle_on",
            "recycle_off",
            "cycle_time",
            "V_tank",
            "c_eluent",
            "c_tank_init",
        ]),
        build=_build,
    )




MODEL_REGISTRY: dict[str, Callable[[ChromatographicColumnBase], ModelSpec]] = {
    "Batch Elution": batch_elution_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
    "CLR": clr_spec,
    "Flip-Flop": flipflop_spec,
    "MRSSR": mrssr_spec,
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
    "diameter":          {"kind": "float",      "default": 0.024,  "min": 0.0,   "units": "m"},
    "bed_porosity":      {"kind": "float",      "default": 0.72,  "min": 0.0, "max": 1.0},
    "length":            {"kind": "float",      "default": 0.5,  "min": 0.0,   "units": "m"},
    "pore_diffusion":    {"kind": "float",      "default": 1e-10, "min": 0.0,   "units": "m^2/s"},
    "film_diffusion":    {"kind": "float",      "default": 1e-3,  "min": 0.0,   "units": "m/s"},
    "particle_porosity": {"kind": "float",      "default": 0.6,  "min": 0.0, "max": 1.0},
    "particle_radius":   {"kind": "float",      "default": 5.0e-6,  "min": 0.0,   "units": "m"},
    "axial_dispersion":  {"kind": "float",      "default": 1e-8,  "min": 0.0,   "units": "m^2/s"},
}

def _infer_kind(x) -> str:
    if isinstance(x, (list, tuple)): return "float_list"
    if isinstance(x, bool):          return "bool"
    return "float"

def _resolve_param(name: str, column_value):
    meta = PARAM_SCHEMA.get(name, {})
    default = meta.get("default", column_value)
    kind    = meta.get("kind", _infer_kind(default))
    transform = parse_float_list if kind == "float_list" else None
    bounds = {k: meta[k] for k in ("min", "max") if k in meta}
    units  = meta.get("units")
    return default, kind, transform, bounds, units

def _coerce_to_kind(kind: str, val):
    if kind == "float_list":
        return parse_float_list(val)
    if kind == "bool":
        return bool(val)
    # default: float
    return float(val)

def build_column_config_spec(column: ChromatographicColumnBase) -> ModelSpec:
    req = getattr(column, "required_parameters", None) or []
    names = _unique_preserve_order(list(req))
    fields: list[FieldSpec] = []

    for name in names:
        col_val = getattr(column, name, None)
        default, kind, transform, bounds, units = _resolve_param(name, col_val)
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
                    # last-resort inference from current column value
                    cur = getattr(column, name, None)
                    kind = _infer_kind(cur)
                coerced = _coerce_to_kind(kind, values[name])
                setattr(column, name, coerced)
            except Exception:
                # swallow and continue so one bad value doesn't block the rest
                continue
        return column

    return ModelSpec(
        title=f"Configure {column.__class__.__name__}",
        fields=fields,
        build=_apply,  # <- pass the function directly; it takes (values)
    )
