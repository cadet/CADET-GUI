from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, Optional, Dict

from CADETProcess.processModel import (
    ChromatographicColumnBase,
    ComponentSystem,
    GeneralRateModel,
    LumpedRateModelWithPores,
    Cstr
)

FieldKind = str
Validator = Callable[[Any], None]
Transform = Callable[[Any], Any]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    label: Optional[str] = None
    default: Any = None
    help: Optional[str] = None
    validate: Optional[Validator] = None
    transform: Optional[Transform] = None


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
    "c_feed": FieldSpec("c_feed", "float_list", "Feed concentration", [1.0], transform=parse_float_list),
    "c_load": FieldSpec("c_load", "float_list", "Load concentration", [1.0], transform=parse_float_list),
    "c_salt_low": FieldSpec("c_salt_low", "float_list", "Low-salt buffer", [0.0], transform=parse_float_list),
    "c_salt_high": FieldSpec("c_salt_high", "float_list", "High-salt buffer", [1.0], transform=parse_float_list),
    "flow_rate": FieldSpec("flow_rate", "float", "Flow rate", 1.0, validate=require_positive),
    "feed_duration": FieldSpec("feed_duration", "float", "Feed duration", 10.0, validate=require_positive),
    "load_duration": FieldSpec("load_duration", "float", "Load duration", 10.0, validate=require_positive),
    "cycle_time": FieldSpec("cycle_time", "float", "Cycle time", 100.0, validate=require_positive),
    "wash_duration": FieldSpec("wash_duration", "float", "Wash duration", 10.0, validate=require_positive),
    "gradient_duration": FieldSpec("gradient_duration", "float", "Gradient duration", 30.0, validate=require_positive),
    "final_wash_duration": FieldSpec("final_wash_duration", "float", "Final wash duration", 0.0),
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
        # Import here to keep module import cheap
        from CADETProcess.modelBuilder import BatchElution
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
        from CADETProcess.modelBuilder import LWE
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


# A simple registry the UI can use to populate the model picker.
# Keys are user-facing names; values are callables: (column) -> ModelSpec
MODEL_REGISTRY: dict[str, Callable[[ChromatographicColumnBase], ModelSpec]] = {
    "Batch Elution": batch_elution_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
    # Add more later, e.g. "SMB": smb_spec, ...
}


# ---- Column factories (receive a ComponentSystem and return a column) ----
ColumnFactory = Callable[[ComponentSystem], ChromatographicColumnBase]


def make_grm(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = GeneralRateModel(cs, name="GRM")
    # Set minimal required parameters as needed, e.g.:
    # col.length = 0.10
    return col


def make_lrmp(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = LumpedRateModelWithPores(cs, name="LRMP")
    # col.length = 0.05
    return col


def make_cstr(cs: ComponentSystem) -> ChromatographicColumnBase:
    col = Cstr(cs, name="CSTR")
    return col


# Register default factories here
DEFAULT_COLUMN_FACTORIES: Dict[str, ColumnFactory] = {
    "GRM": make_grm,
    "LRMP": make_lrmp,
    "CSTR": make_cstr,
    # "TubularReactor": make_tubular(...),
    # "MCT": make_mct(...),
}

# --- Dynamic column configuration from required_parameters ---

# Optional overrides: parameter name -> FieldKind (e.g., "float", "float_list", "bool", "text")
# For now we default everything to "float", but you can override per name here.
PARAM_TYPE_OVERRIDES: Dict[str, FieldKind] = {
    # "length": "float",
    # "diameter": "float",
    # "porosity_bed": "float",
    # "porosity_pore": "float",
    # "volume": "float",
}

def column_spec_from_required(column: ChromatographicColumnBase) -> ModelSpec:
    """
    Build a ModelSpec for a column by reflecting over column.required_parameters.
    Defaults each field to kind='float' unless overridden in PARAM_TYPE_OVERRIDES.
    Uses the current attribute value as the default if present.
    """
    req = getattr(column, "required_parameters", None)
    if not req:
        # Fallback: nothing to configure
        return ModelSpec(
            title=f"Configure {column.__class__.__name__}",
            fields=[],
            build=lambda _v: column,
        )

    fields: list[FieldSpec] = []
    for name in req:
        kind = PARAM_TYPE_OVERRIDES.get(name, "float")  # default everything to float for now
        default = getattr(column, name, None)
        label = name.replace("_", " ").capitalize()
        # You can extend with validation/transform per kind if you like.
        fields.append(FieldSpec(name=name, kind=kind, label=label, default=default))

    def _apply(v: Mapping[str, Any]) -> Any:
        # Assign back to the column
        for name in req:
            if name in v:
                try:
                    if PARAM_TYPE_OVERRIDES.get(name, "float") == "float":
                        setattr(column, name, float(v[name]))
                    else:
                        # room for future kinds
                        setattr(column, name, v[name])
                except Exception:
                    # keep going even if a parameter fails to set
                    pass
        return column

    return ModelSpec(
        title=f"Configure {column.__class__.__name__}",
        fields=fields,
        build=_apply,
    )
