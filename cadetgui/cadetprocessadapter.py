from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Sequence

from CADETProcess.instruments import (
    LWE,
    Breakthrough,
    LCFlowSheet,
    PulseInjection,
    Step,
    StepElution,
)
from CADETProcess.processModel import (
    BindingBaseClass,
    ChromatographicColumnBase,
    ComponentSystem,
    Cstr,
    FlowSheet,
    GeneralRateModel,
    Inlet,
    Langmuir,
    Linear,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    Outlet,
    Process,
    StericMassAction,
    TubularReactorBase,
)

from .parameters import get_parameters as _param_metadata_for

Validator = Callable[[Any], None]
Transform = Callable[[Any], Any]


@dataclass(frozen=True)
class FieldSpec:
    """Describes one form field: its kind, default, bounds, and validation."""

    name: str
    kind: Literal["float", "float_list", "bool", "text", "choice"]
    label: str | None = None
    default: Any = None
    transform: Callable | None = None
    validate: Optional[Validator] = None
    min: float | None = None
    max: float | None = None
    units: str | None = None
    component_names: tuple[str, ...] | None = None
    # "choice" only: (label, value) options for the dropdown.
    options: tuple[tuple[str, Any], ...] | None = None


def require_positive(x: Any) -> None:
    """Raise ValueError unless x is a positive number."""
    if float(x) <= 0:
        raise ValueError("Must be > 0.")


def require_finite_above(minimum: float = 0.0, *, inclusive: bool = False) -> Validator:
    """Return a validator rejecting NaN/inf and values below (or at, unless inclusive) `minimum`."""

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
    s = str(v)
    vals: list[float] = []
    for chunk in s.replace(";", ",").replace("\n", " ").split(","):
        for tok in chunk.split():
            if tok:
                vals.append(float(tok))
    return vals


CONCENTRATION_UNITS = r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{IV}}}"

# Units: mol/m^3 interstitial (inlet.rst CONST_COEFF), s (solver.rst SECTION_TIMES),
# flow_rate m^3/s by consistency with CADET-Core's other flow-rate fields.
#
# Concentration fields (c_buffer_a, c_buffer_b, c_sample) aren't here --
# they're per-component (`Inlet.c`), built by `_concentration_field()` per
# model-spec call instead.
PARAMS: dict[str, FieldSpec] = {
    "flow_rate": FieldSpec(
        "flow_rate", "float", "Flow rate", 1.0e-6,
        validate=require_positive, units=r"\frac{\mathrm{m}^{3}}{\mathrm{s}}",
    ),
    "flow_rate_wash": FieldSpec(
        "flow_rate_wash", "float", "Flow rate", 1.0e-6,
        validate=require_positive, units=r"\frac{\mathrm{m}^{3}}{\mathrm{s}}",
    ),
    "cycle_time": FieldSpec(
        "cycle_time", "float", "Cycle time", 6000.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "pulse_duration": FieldSpec(
        "pulse_duration", "float", "Pulse duration", 60.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_wash": FieldSpec(
        "delta_t_wash", "float", "Wash duration", 600.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_elute": FieldSpec(
        "delta_t_elute", "float", "Elution duration", 1200.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_final_wash": FieldSpec(
        "delta_t_final_wash", "float", "Final wash duration", 600.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
}


@dataclass
class ModelSpec:
    """A titled group of fields plus the build function that consumes their values."""

    title: str
    fields: list[FieldSpec] = field(default_factory=list)
    build: Callable[[Mapping[str, Any]], Any] | None = None
    # Standalone (no-Instrument) templates wire their own FlowSheet directly --
    # there's no LCFlowSheet/model-builder class for a bare feed-into-unit
    # setup -- so `export_script()` uses this instead of its LCFlowSheet-based
    # default pattern when set. None for every INSTRUMENT_TEMPLATES entry.
    export: Callable[[Mapping[str, Any]], list[str]] | None = None


def _pick(keys: Sequence[str]) -> list[FieldSpec]:
    return [PARAMS[k] for k in keys]


def _concentration_field(
    name: str, label: str, default_scalar: float, component_system: ComponentSystem
) -> FieldSpec:
    """Per-component concentration field, sized/named from the given ComponentSystem."""
    names = tuple(component_system.names)
    n_comp = len(names) or 1
    return FieldSpec(
        name, "float_list", label, [default_scalar] * n_comp,
        transform=parse_float_list, units=CONCENTRATION_UNITS, component_names=names,
    )


def pulse_injection_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Pulse Injection template's ModelSpec for the given instrument."""
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return PulseInjection(
            "pulse_injection", flow_sheet,
            c_buffer_a=v["c_buffer_a"],
            c_sample=v["c_sample"],
            cycle_time=float(v["cycle_time"]),
            flow_rate=float(v["flow_rate"]),
        )

    fields = [
        _concentration_field("c_buffer_a", "Buffer A concentration", 0.0, cs),
        _concentration_field("c_sample", "Sample concentration", 10.0, cs),
        *_pick(["cycle_time", "flow_rate"]),
    ]
    return ModelSpec(title="Pulse Injection", fields=fields, build=_build)


def step_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Step template's ModelSpec for the given instrument."""
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return Step(
            "step", flow_sheet,
            c_buffer_a=v["c_buffer_a"],
            c_buffer_b=v["c_buffer_b"],
            cycle_time=float(v["cycle_time"]),
            flow_rate=float(v["flow_rate"]),
        )

    fields = [
        _concentration_field("c_buffer_a", "Buffer A concentration", 0.0, cs),
        _concentration_field("c_buffer_b", "Buffer B concentration", 1000.0, cs),
        *_pick(["cycle_time", "flow_rate"]),
    ]
    return ModelSpec(title="Step", fields=fields, build=_build)


def lwe_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Load-Wash-Elute template's ModelSpec for the given instrument.

    `flow_rate_elute`/`flow_rate_final_wash` aren't exposed separately here --
    both default to `flow_rate_wash` (CADET-Process's own default), a
    deliberately narrower slice than the full three-flow-rate constructor.
    """
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return LWE(
            "lwe", flow_sheet,
            c_buffer_a=v["c_buffer_a"],
            c_buffer_b=v["c_buffer_b"],
            c_sample=v["c_sample"],
            delta_t_wash=float(v["delta_t_wash"]),
            delta_t_elute=float(v["delta_t_elute"]),
            delta_t_final_wash=float(v["delta_t_final_wash"]),
            flow_rate_wash=float(v["flow_rate_wash"]),
        )

    fields = [
        _concentration_field("c_buffer_a", "Buffer A concentration", 20.0, cs),
        _concentration_field("c_buffer_b", "Buffer B concentration", 1000.0, cs),
        _concentration_field("c_sample", "Sample concentration", 20.0, cs),
        *_pick(["delta_t_wash", "delta_t_elute", "delta_t_final_wash", "flow_rate_wash"]),
    ]
    return ModelSpec(title="Load–Wash–Elute (LWE)", fields=fields, build=_build)


def step_elution_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Step Elution template's ModelSpec for the given instrument.

    Same scope note as `lwe_spec`: only `flow_rate_wash` is exposed.
    """
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return StepElution(
            "step_elution", flow_sheet,
            c_buffer_a=v["c_buffer_a"],
            c_buffer_b=v["c_buffer_b"],
            c_sample=v["c_sample"],
            delta_t_wash=float(v["delta_t_wash"]),
            delta_t_elute=float(v["delta_t_elute"]),
            delta_t_final_wash=float(v["delta_t_final_wash"]),
            flow_rate_wash=float(v["flow_rate_wash"]),
        )

    fields = [
        _concentration_field("c_buffer_a", "Buffer A concentration", 20.0, cs),
        _concentration_field("c_buffer_b", "Buffer B concentration", 1000.0, cs),
        _concentration_field("c_sample", "Sample concentration", 20.0, cs),
        *_pick(["delta_t_wash", "delta_t_elute", "delta_t_final_wash", "flow_rate_wash"]),
    ]
    return ModelSpec(title="Step Elution", fields=fields, build=_build)


def breakthrough_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Breakthrough template's ModelSpec for the given instrument."""
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return Breakthrough(
            "breakthrough", flow_sheet,
            c_sample=v["c_sample"],
            flow_rate=float(v["flow_rate"]),
            cycle_time=float(v["cycle_time"]),
            sample_buffer=v["sample_buffer"],
        )

    fields = [
        _concentration_field("c_sample", "Sample concentration", 10.0, cs),
        *_pick(["flow_rate", "cycle_time"]),
        FieldSpec(
            "sample_buffer", "choice", "Sample delivered via", "F",
            options=(
                ("Feed inlet (F)", "F"), ("Buffer A", "A"), ("Buffer B", "B"),
                ("Buffer C", "C"), ("Buffer D", "D"),
            ),
        ),
    ]
    return ModelSpec(title="Breakthrough", fields=fields, build=_build)


def pulse_feed_spec(unit: Any) -> ModelSpec:
    """Build the standalone Pulse Feed template's ModelSpec for a bare column/unit.

    Used only when `ConfigurationWidget` has no InstrumentWidget bound -- there
    is no CADET-Process model-builder class for a plain feed-into-unit setup
    (unlike LCFlowSheet's own richer templates), so this wires a minimal
    `FlowSheet` (feed -> unit -> outlet) directly, with the same primitives
    `LCFlowSheet` itself is built from. Works with any unit operation, not
    just a `ChromatographicColumnBase` -- e.g. `Cstr`, which can never be an
    `LCFlowSheet` column but is a perfectly good standalone simulation target.
    """
    names = tuple(unit.component_system.names)

    def _c_feed(v: Mapping[str, Any]) -> list[float]:
        c_feed = [0.0] * (len(names) or 1)
        if v["component"] in names:
            c_feed[names.index(v["component"])] = float(v["concentration"])
        return c_feed

    def _build(v: Mapping[str, Any]) -> Any:
        component_system = unit.component_system
        feed = Inlet(component_system, name="feed")
        feed.flow_rate = float(v["flow_rate"])
        outlet = Outlet(component_system, name="outlet")

        flow_sheet = FlowSheet(component_system)
        flow_sheet.add_unit(feed, feed_inlet=True)
        flow_sheet.add_unit(unit)
        flow_sheet.add_unit(outlet, product_outlet=True)
        flow_sheet.add_connection(feed, unit)
        flow_sheet.add_connection(unit, outlet)

        process = Process(flow_sheet, "pulse_feed")
        process.cycle_time = float(v["cycle_time"])
        process.add_duration("pulse_duration", float(v["pulse_duration"]))

        c_feed = _c_feed(v)
        process.add_event("pulse_on", "flow_sheet.feed.c", c_feed)
        process.add_event("pulse_off", "flow_sheet.feed.c", [0.0] * len(c_feed))
        process.add_event_dependency("pulse_off", ["pulse_on", "pulse_duration"], [1, 1])
        return process

    def _export(v: Mapping[str, Any]) -> list[str]:
        c_feed = _c_feed(v)
        c_off = [0.0] * len(c_feed)
        return [
            "",
            "feed = Inlet(component_system, name='feed')",
            f"feed.flow_rate = {float(v['flow_rate'])!r}",
            "outlet = Outlet(component_system, name='outlet')",
            "",
            "flow_sheet = FlowSheet(component_system)",
            "flow_sheet.add_unit(feed, feed_inlet=True)",
            "flow_sheet.add_unit(column)",
            "flow_sheet.add_unit(outlet, product_outlet=True)",
            "flow_sheet.add_connection(feed, column)",
            "flow_sheet.add_connection(column, outlet)",
            "",
            "process = Process(flow_sheet, 'pulse_feed')",
            f"process.cycle_time = {float(v['cycle_time'])!r}",
            f"process.add_duration('pulse_duration', {float(v['pulse_duration'])!r})",
            f"process.add_event('pulse_on', 'flow_sheet.feed.c', {c_feed!r})",
            f"process.add_event('pulse_off', 'flow_sheet.feed.c', {c_off!r})",
            "process.add_event_dependency('pulse_off', ['pulse_on', 'pulse_duration'], [1, 1])",
        ]

    fields = [
        FieldSpec(
            "component", "choice", "Component", names[0] if names else None,
            options=tuple((n, n) for n in names),
        ),
        FieldSpec(
            "concentration", "float", "Pulse concentration", 10.0, units=CONCENTRATION_UNITS,
        ),
        *_pick(["flow_rate", "pulse_duration", "cycle_time"]),
    ]
    return ModelSpec(
        title="Pulse Feed (Single Component)", fields=fields, build=_build, export=_export
    )


# PhasedProcess's fully generic phase-list composition is out of scope here --
# see REQUIREMENTS.md's "generic user-authored event widget" open decision.
INSTRUMENT_TEMPLATES: dict[str, Callable[[LCFlowSheet], ModelSpec]] = {
    "Pulse Injection": pulse_injection_spec,
    "Step": step_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
    "Step Elution": step_elution_spec,
    "Breakthrough": breakthrough_spec,
}

# Used instead of INSTRUMENT_TEMPLATES when ConfigurationWidget has no
# InstrumentWidget bound -- REQUIREMENTS.md item #32 ("instrument attachment
# optional, not required for a simple simulation"). Deliberately one entry for
# now, matching this codebase's narrow-slice-first pattern; extend when a
# second bare-column workflow is actually needed.
STANDALONE_TEMPLATES: dict[str, Callable[[Any], ModelSpec]] = {
    "Pulse Feed (Single Component)": pulse_feed_spec,
}

# Units `LCFlowSheet(bypass_units=...)` accepts (CADET-Process's own
# `_BYPASSABLE` set, not exported -- mirrored here rather than reached into).
BYPASSABLE_UNITS: tuple[str, ...] = (
    "mixer", "tubing_pre_injection", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors",
)

# `LCFlowSheet(ColumnModel=...)` takes the class itself -- it instantiates and
# names the column ("column") internally, so this is a plain class registry,
# not an instance-factory like the old `DEFAULT_COLUMN_FACTORIES`. CSTR is
# back (REQUIREMENTS.md item #32) since it's a real, useful standalone
# simulation target -- it's just never offered once an Instrument is bound
# (see INSTRUMENT_COMPATIBLE_COLUMNS below), since it isn't a
# `ChromatographicColumnBase` and doesn't fit LCFlowSheet's column slot.
COLUMN_MODELS: Dict[str, type] = {
    "General Rate Model (GRM)": GeneralRateModel,
    "Lumped Rate Model With Pores (LRMP)": LumpedRateModelWithPores,
    "Lumped Rate Model Without Pores (LRM)": LumpedRateModelWithoutPores,
    "Continuous Stirred Tank Reactor (CSTR)": Cstr,
}

# Derived, not hand-maintained -- a column model is instrument-compatible iff
# it's a real ChromatographicColumnBase (LCFlowSheet's own constraint).
INSTRUMENT_COMPATIBLE_COLUMNS: frozenset[str] = frozenset(
    key for key, cls in COLUMN_MODELS.items() if issubclass(cls, ChromatographicColumnBase)
)

# "None" first so a ChoiceField over this dict defaults to it -- LCFlowSheet
# leaves the column's own default (NoBinding) in place when BindingModel=None.
BINDING_MODELS: Dict[str, Optional[type]] = {
    "None": None,
    "Linear": Linear,
    "Langmuir": Langmuir,
    "Steric Mass Action (SMA)": StericMassAction,
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
    ("column", None, "total_porosity"): 0.72,
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

# `TubularReactor.axial_dispersion` is genuinely component-dependent at the
# CADET-Process level (same SizedUnsignedList(size="n_comp") as a real
# column's, confirmed directly) -- but a plain tubing/mixer dead-volume
# segment gets no multiplex toggle at all, unlike MULTIPLEXABLE_COLUMN_PARAMS
# above, so it must never render as a per-component list regardless of
# `multiplex`. A GUI-layer decision (which fields to render, how), so it
# lives here rather than in cadetgui/parameters.
_FORCE_SCALAR = frozenset({("TubularReactor", "axial_dispersion")})


def _category_and_model(obj: Any) -> tuple[Optional[str], str]:
    model_name = type(obj).__name__
    if isinstance(obj, BindingBaseClass):
        return "binding", model_name
    # TubularReactorBase covers both real columns (ChromatographicColumnBase,
    # its subclass) and plain tubing/mixer dead-volume segments (TubularReactor
    # itself, which shares the same length/diameter/axial_dispersion
    # descriptors, inherited from TubularReactorBase).
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
    """Resolve one parameter's kind/bounds/units/default.

    Ground truth comes from `parameters.get_parameters()` via
    `category`/`model_name` (nested per-model, since e.g. `Langmuir.capacity`
    and `StericMassAction.capacity` differ in shape despite the same name) --
    `component_dependent`/`dtype`/bounds/`unit` are all introspected live off
    the real CADET-Process descriptor there, not hand-typed.
    Falls back to inferring from the object's current value for an
    unregistered category/model/parameter, or one live introspection
    couldn't resolve a real descriptor for. `multiplex` overrides
    `component_dependent` for `MULTIPLEXABLE_COLUMN_PARAMS` only;
    `_FORCE_SCALAR` overrides it unconditionally for names that must never
    render per-component regardless of `multiplex`.
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
    obj: Any, *, multiplex: Optional[Dict[str, bool]] = None, include_optional: bool = False
) -> ModelSpec:
    """Build a ModelSpec from any object exposing `required_parameters`.

    Generic over `obj` (column, binding model, ...) so the same function
    drives every form. `multiplex` only matters for
    `MULTIPLEXABLE_COLUMN_PARAMS`. `include_optional` also renders every
    scalar/list parameter `obj` currently holds a value for, beyond
    `required_parameters`.
    """
    req = getattr(obj, "required_parameters", None) or []
    names = _unique_preserve_order(list(req))
    category, model_name = _category_and_model(obj)

    # `obj.required_parameters` is a CADET-Process class-level property whose
    # *order* is not stable across process runs: its metaclass builds it via
    # `list(set(parameters))` (CADETProcess/dataStructure/dataStructure.py),
    # so which parameter lands first depends on Python's per-process string
    # hash seed -- confirmed by observing `total_porosity` and
    # `axial_dispersion` swap which one is index 0 between separate `python`
    # invocations of the identical code. The *set* of names is correct, only
    # the order isn't. Sorting alphabetically sidesteps the hash-seed
    # randomness entirely, giving a stable rendered field/checklist order
    # without needing a curated ordering anywhere.
    names.sort()

    # is_kinetic isn't in CADET-Process's own required_parameters, but every
    # binding model with a real isotherm needs it settable. `names` is only
    # non-empty for those (NoBinding's required_parameters is []).
    if category == "binding" and names:
        names.append("is_kinetic")

    if include_optional:
        # obj.parameters' values are frozen at construction time, not live --
        # read each one fresh via getattr. Structured (dict-valued)
        # parameters aren't renderable by this generic per-parameter form.
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


def classify_signal_ports(result: Any) -> list[tuple[str, tuple[str, str]]]:
    """List (label, (unit, port)) solution signals, collapsed for Inlet/Outlet units.

    An `Inlet`'s "inlet" port and an `Outlet`'s "outlet" port are CADET-Process
    bookkeeping, not real signals -- identical to that same unit's other port
    for every current template. Only the real port is offered, labeled
    "Source"/"Sink" rather than the (there, meaningless) port name.

    Any "Sink" entry is sorted first -- comparing/fitting against the process
    outlet is the common case (`ChoiceField.set_options(..., keep_value=True)`
    defaults to index 0 when nothing was previously selected, so this is what
    determines the signal picker's default in both `SolutionWidget` and
    `ParameterEstimationWidget`). An `LCFlowSheet` always has two Outlets
    (`outlet`, the product; `waste`) -- the unit literally named `"outlet"` is
    sorted first among sinks, not just "any Outlet", so `waste` stays a valid
    but secondary choice rather than competing for the default.
    """
    return _order_signal_ports(
        result.process.flow_sheet.units_dict,
        {name: list(ports) for name, ports in result.solution.items()},
    )


def list_signal_ports(process: Any) -> list[tuple[str, tuple[str, str]]]:
    """Derive the `classify_signal_ports` list from a process without simulating it."""
    units = process.flow_sheet.units_dict
    ports_by_unit = {
        name: [
            port
            for port in ("inlet", "outlet", "volume")
            if getattr(unit.solution_recorder, f"write_solution_{port}", port != "volume")
        ]
        for name, unit in units.items()
    }
    return _order_signal_ports(units, ports_by_unit)


def _order_signal_ports(
    units: Mapping[str, Any], ports_by_unit: Mapping[str, Sequence[str]]
) -> list[tuple[str, tuple[str, str]]]:
    sinks: list[tuple[str, str, tuple[str, str]]] = []
    others: list[tuple[str, tuple[str, str]]] = []
    for unit_name, ports in ports_by_unit.items():
        unit = units.get(unit_name)
        if isinstance(unit, Inlet):
            if "outlet" in ports:
                others.append((f"{unit_name}: Source", (unit_name, "outlet")))
        elif isinstance(unit, Outlet):
            if "inlet" in ports:
                sinks.append((unit_name, f"{unit_name}: Sink", (unit_name, "inlet")))
        else:
            for port in ports:
                others.append((f"{unit_name}: {port}", (unit_name, port)))
    sinks.sort(key=lambda entry: entry[0] != "outlet")
    return [(label, value) for _, label, value in sinks] + others
