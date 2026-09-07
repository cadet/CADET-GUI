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


# Units sourced from CADET-Core docs (interface/unit_operations/inlet.rst's
# CONST_COEFF for concentrations: mol/m_IV^-3; interface/solver.rst's
# SECTION_TIMES for durations: s). `flow_rate`'s m^3/s isn't documented for
# this exact field (Inlet-to-column connection flow rate isn't itemized in
# system.rst), but is the one volumetric-flow-rate unit CADET-Core uses
# consistently everywhere else (e.g. CSTR's FLOWRATE_FILTER) -- inferred by
# consistency, not invented, and noted here rather than silently assumed.
#
# Concentration fields (c_feed, c_load, c_salt_low, c_salt_high, c_eluent) are
# NOT in this dict -- they're genuinely per-component (`Inlet.c`), so they're
# built fresh per model-spec call by `_concentration_field()`, sized/named
# from the actual column's ComponentSystem, same as column/binding parameters.
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


def _unique_preserve_order(names: Sequence[str]) -> list[str]:
    """Return names in original order, dropping duplicates (first occurrence wins)."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _infer_kind(x) -> str:
    if isinstance(x, (list, tuple)): return "float_list"
    if isinstance(x, bool): return "bool"
    return "float"


# GUI-only seed defaults: a sensible starting value for a blank form, so
# "Apply" without touching anything doesn't build a degenerate (zero-length,
# zero-porosity) column. CADET-Core has no canonical default for these --
# they're mandatory, problem-specific physical inputs -- so this deliberately
# lives here rather than in parameters/interface.json (which is the ground-truth
# CADET-Process<->CADET-Core mapping, not a GUI convenience). Shared across
# column models via the `None` model slot; add a `(category, "ModelName", name)`
# entry only if a specific model genuinely needs a different seed.
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


# Column parameters CADET-Process treats as genuinely per-component
# (`SizedUnsignedList(size="n_comp")`, confirmed in ai-docs/ARCHITECTURE.md's
# "Parameter metadata schema" notes) but that most users want to enter as one
# shared value most of the time -- unlike binding-model parameters (rates,
# capacities, ...), which are per-component almost always by physical
# necessity. `ConfigurationWidget`'s multiplex toggle (gear icon on the
# Column Model section) offers these three as opt-in per-component editors;
# everywhere else they default to a single scalar that CADET-Process itself
# broadcasts to every component (confirmed: `col.axial_dispersion = 1e-8` ->
# `[1e-8, 1e-8, 1e-8]` for a 3-component system) -- not a GUI approximation,
# the real CADET-Process setter behavior.
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
):
    """Resolve one parameter's kind/bounds/units/default.

    Ground truth (kind, bounds, units, whether it's per-component) comes from
    `parameters/interface.json` via `category`/`model_name` -- see
    ai-docs/ARCHITECTURE.md's "Parameter metadata schema" for why this is
    nested per-model rather than one flat dict (e.g. `Langmuir.capacity` is
    per-component, `StericMassAction.capacity` is a single scalar; same
    CADET-Process attribute name, different shape). Falls back to inferring
    purely from the object's current value when the schema doesn't (yet) know
    this category/model/parameter, so an unregistered model still renders
    something instead of raising.

    `multiplex` overrides `component_dependent` for names in
    `MULTIPLEXABLE_COLUMN_PARAMS` -- everywhere else the schema's own flag
    (ground truth, not a GUI choice) decides.
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
        # CADET-Process always stores these as a per-component list internally,
        # even when it was set via scalar broadcast -- if multiplex was just
        # toggled off, `current` is still that list. "multiplex off" means
        # "one value for every component," so the first entry is the
        # representative scalar (matches how it would've been entered).
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


def _coerce_to_kind(kind: str, val):
    if kind == "float_list":
        return parse_float_list(val)
    if kind == "bool":
        return bool(val)
    # default: float
    return float(val)


def build_parameter_config_spec(
    obj: Any, *, multiplex: Optional[Dict[str, bool]] = None
) -> ModelSpec:
    """Build a ModelSpec from any object exposing `required_parameters`.

    Generic over what `obj` is — a column, a binding model, anything with the
    CADET-Process `required_parameters` convention — so the same function
    drives both the column form and the binding-model form.

    `multiplex`: see `MULTIPLEXABLE_COLUMN_PARAMS` — only meaningful for the
    column category's `axial_dispersion`/`film_diffusion`/`pore_diffusion`;
    ignored (and unnecessary) for everything else, which always renders
    per-component when the schema says it's component-dependent.
    """
    req = getattr(obj, "required_parameters", None) or []
    names = _unique_preserve_order(list(req))
    category, model_name = _category_and_model(obj)
    component_names = tuple(obj.component_system.names) if hasattr(obj, "component_system") else ()
    fields: list[FieldSpec] = []
    kinds: dict[str, str] = {}

    for name in names:
        default, kind, transform, bounds, units = _resolve_param(
            obj, category, model_name, name, multiplex=multiplex
        )
        kinds[name] = kind
        label = name.replace("_", " ").capitalize()
        fs_kwargs = dict(name=name, kind=kind, label=label, default=default, transform=transform, **bounds)
        if units is not None:
            fs_kwargs["units"] = units
        if kind == "float_list" and component_names:
            fs_kwargs["component_names"] = component_names
        fields.append(FieldSpec(**fs_kwargs))

    def _apply(values: Mapping[str, Any]) -> Any:
        for name in names:
            if name not in values:
                continue
            try:
                coerced = _coerce_to_kind(kinds[name], values[name])
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
