from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Dict, Literal, Mapping, Optional, Sequence

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


CONCENTRATION_UNITS = r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{IV}}}"

# Shared scalar process fields (m^3/s, s). Per-component concentration fields are built
# by `_concentration_field` instead, since they depend on the component system.
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
    # Script lines for standalone templates that wire their own FlowSheet; None otherwise.
    export: Callable[[Mapping[str, Any]], list[str]] | None = None
    # Display names of the `PhasedProcess` phases, in order.
    phase_names: tuple[str, ...] = ()


def _pick(keys: Sequence[str]) -> list[FieldSpec]:
    return [PARAMS[k] for k in keys]


def _concentration_field(
    name: str, label: str, default_scalar: float, component_system: ComponentSystem
) -> FieldSpec:
    """Return a per-component concentration field sized from `component_system`."""
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
    return ModelSpec(
        title="Pulse Injection", fields=fields, build=_build, phase_names=("Pulse injection",)
    )


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
    return ModelSpec(title="Step", fields=fields, build=_build, phase_names=("Step",))


def _wash_elute_spec(
    flow_sheet: LCFlowSheet, template: type, name: str, title: str, phase_names: tuple[str, ...]
) -> ModelSpec:
    """Build the shared wash/elute/final-wash spec; only `flow_rate_wash` is exposed."""
    cs = flow_sheet.component_system

    def _build(v: Mapping[str, Any]) -> Any:
        return template(
            name, flow_sheet,
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
    return ModelSpec(title=title, fields=fields, build=_build, phase_names=phase_names)


def lwe_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Load-Wash-Elute template's ModelSpec for the given instrument."""
    return _wash_elute_spec(
        flow_sheet, LWE, "lwe", "Load–Wash–Elute (LWE)",
        ("Wash", "Elute (gradient)", "Final wash"),
    )


def step_elution_spec(flow_sheet: LCFlowSheet) -> ModelSpec:
    """Build the Step Elution template's ModelSpec for the given instrument."""
    return _wash_elute_spec(
        flow_sheet, StepElution, "step_elution", "Step Elution", ("Wash", "Elute", "Final wash")
    )


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
    return ModelSpec(
        title="Breakthrough", fields=fields, build=_build, phase_names=("Breakthrough",)
    )


def pulse_feed_spec(unit: Any) -> ModelSpec:
    """Build the standalone Pulse Feed ModelSpec: a minimal feed -> `unit` -> outlet flow sheet.

    Works with any unit operation, including a `Cstr`, which no `LCFlowSheet` accepts.
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


_PHASE_EVENT = re.compile(r"^phase_(\d+)_")
_SAMPLE_INJECTION_EVENT = re.compile(r"^valve_sample_loop_inject(_\d+)?$")


def process_phase_spans(process: Any, names: Sequence[str] = ()) -> list[dict[str, Any]]:
    """`PhasedProcess` phases as `{"name", "start", "end"}` dicts in seconds.

    Phases are recovered from the `phase_<i>_<buffer>` events `PhasedProcess`
    emits; a phase ends where the next one starts (the last, at `cycle_time`).
    `names` are applied only when there is one per phase, else "Phase <i>".
    Processes without phase events give an empty list.
    """
    starts: dict[int, float] = {}
    for event in process.events:
        match = _PHASE_EVENT.match(event.name)
        if match:
            i = int(match.group(1))
            starts[i] = min(float(event.time), starts.get(i, math.inf))
    if not starts:
        return []
    order = sorted(starts)
    named = len(names) == len(order)
    spans = []
    for pos, i in enumerate(order):
        end = starts[order[pos + 1]] if pos + 1 < len(order) else float(process.cycle_time)
        spans.append(
            {"name": names[pos] if named else f"Phase {pos + 1}", "start": starts[i], "end": end}
        )
    return spans


def sample_injection_times(process: Any) -> list[float]:
    """Return the times (s) at which the process switches the sample loop into the flow path."""
    return sorted(
        float(e.time) for e in process.events if _SAMPLE_INJECTION_EVENT.match(e.name)
    )


INSTRUMENT_TEMPLATES: dict[str, Callable[[LCFlowSheet], ModelSpec]] = {
    "Breakthrough": breakthrough_spec,
    "Step": step_spec,
    "Pulse Injection": pulse_injection_spec,
    "Load–Wash–Elute (LWE)": lwe_spec,
    "Step Elution": step_elution_spec,
}

_TEMPLATE_REQUIRED_UNITS: dict[Callable[..., ModelSpec], frozenset[str]] = {
    pulse_injection_spec: frozenset({"sample_loop"}),
    lwe_spec: frozenset({"sample_loop"}),
    step_elution_spec: frozenset({"sample_loop"}),
}


def template_required_units(template: Callable[..., ModelSpec] | None) -> frozenset[str]:
    """Flow-path units a process template can't be built without (`"sample_loop"`)."""
    return _TEMPLATE_REQUIRED_UNITS.get(template, frozenset())


# Used instead of INSTRUMENT_TEMPLATES when no InstrumentWidget is bound.
STANDALONE_TEMPLATES: dict[str, Callable[[Any], ModelSpec]] = {
    "Pulse Feed (Single Component)": pulse_feed_spec,
}

# Units `LCFlowSheet(bypass_units=...)` accepts (mirrors its unexported `_BYPASSABLE`).
BYPASSABLE_UNITS: tuple[str, ...] = (
    "mixer", "tubing_pre_injection", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors",
)

# Plain names for every LCFlowSheet unit.
UNIT_LABELS: dict[str, str] = {
    "buffer_a": "Buffer A",
    "buffer_b": "Buffer B",
    "buffer_c": "Buffer C",
    "buffer_d": "Buffer D",
    "feed_inlet": "Feed",
    "mixer": "Mixer",
    "tubing_pre_injection": "Tubing (pre injection)",
    "sample_loop": "Sample loop",
    "tubing_pre_column": "Tubing (pre column)",
    "column": "Column",
    "tubing_post_column": "Tubing (post column)",
    "tubing_detectors": "Tubing (detectors)",
    "outlet": "Outlet",
    "waste": "Waste outlet",
}

_INLET_UNITS = ("buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet")


def active_inlets(process: Any) -> list[str]:
    """Names of the LC inlets a process actually drives (a flow-rate event is set on them)."""
    driven = {
        event.parameter_path.split(".")[1]
        for event in process.events
        if event.parameter_path.startswith("flow_sheet.")
        and event.parameter_path.endswith(".flow_rate")
    }
    driven.update(equilibration_inlets(process))
    return [name for name in _INLET_UNITS if name in driven]


def equilibration_inlets(process: Any) -> list[str]:
    """Inlets that only pre-equilibrate the system before the process starts (Step: buffer A)."""
    return ["buffer_a"] if isinstance(process, Step) else []


def inlet_contents(process: Any) -> dict[str, list[str]]:
    """Component names each driven inlet carries; `"sample_loop"` is listed when it holds sample."""
    flow_sheet = process.flow_sheet
    names = list(flow_sheet.component_system.names)
    units = flow_sheet.units_dict
    contents: dict[str, list[str]] = {}
    for name in [*active_inlets(process), "sample_loop"]:
        if name not in units:
            continue
        found = [n for n, c in zip(names, units[name].c) if any(_as_list(c))]
        if found or name != "sample_loop":
            contents[name] = found
    return contents


def _as_list(value: Any) -> list[Any]:
    return list(value) if hasattr(value, "__iter__") else [value]


def signal_label(unit: str, port: str) -> str:
    """Plain-language name of a signal position, e.g. "Column outlet" or "Outlet"."""
    name = UNIT_LABELS.get(unit, unit.replace("_", " ").capitalize())
    if unit in ("outlet", "waste"):
        return name
    if port == "outlet" and unit in _INLET_UNITS:
        return f"{name} inlet"
    return f"{name} {port}"


def friendly_signal_options(
    options: Sequence[tuple[str, tuple[str, str]]],
) -> list[tuple[str, tuple[str, str]]]:
    """Relabel `(label, (unit, port))` signal options with `signal_label`."""
    return [(signal_label(unit, port), (unit, port)) for _, (unit, port) in options]


# `LCFlowSheet(ColumnModel=...)` takes the class itself. CSTR is standalone-only: it is not
# a `ChromatographicColumnBase`, so it does not fit LCFlowSheet's column slot.
COLUMN_MODELS: Dict[str, type] = {
    "General Rate Model (GRM)": GeneralRateModel,
    "Lumped Rate Model With Pores (LRMP)": LumpedRateModelWithPores,
    "Lumped Rate Model Without Pores (LRM)": LumpedRateModelWithoutPores,
    "Continuous Stirred Tank Reactor (CSTR)": Cstr,
}

INSTRUMENT_COMPATIBLE_COLUMNS: frozenset[str] = frozenset(
    key for key, cls in COLUMN_MODELS.items() if issubclass(cls, ChromatographicColumnBase)
)

# "None" first so a ChoiceField defaults to it; LCFlowSheet keeps the column's NoBinding.
BINDING_MODELS: Dict[str, Optional[type]] = {
    "None": None,
    "Linear": Linear,
    "Langmuir": Langmuir,
    "Steric Mass Action (SMA)": StericMassAction,
}


def _infer_kind(x: Any) -> str:
    if isinstance(x, (list, tuple)):
        return "float_list"
    if isinstance(x, bool):
        return "bool"
    return "float"


# Starting values so a blank form doesn't apply a degenerate column. A `None` model slot
# is shared across column models; a model name overrides it.
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


def classify_signal_ports(result: Any) -> list[tuple[str, tuple[str, str]]]:
    """List the simulated `(label, (unit, port))` signals, with sinks first.

    An Inlet's "inlet" port and an Outlet's "outlet" port are bookkeeping, so only the
    real port is offered, labelled "Source"/"Sink". The unit named `"outlet"` leads the
    sinks, which makes it the signal pickers' default over `waste`.
    """
    return _order_signal_ports(
        result.process.flow_sheet.units_dict,
        {name: list(ports) for name, ports in result.solution.items()},
    )


def list_signal_ports(process: Any) -> list[tuple[str, tuple[str, str]]]:
    """Return the `classify_signal_ports` list for a process without simulating it."""
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


# Fluid-moving hardware where nothing is measured.
_INFRASTRUCTURE_UNITS = ("mixer", "sample_loop")


def measurable_signal_ports(
    units: Mapping[str, Any],
    options: Sequence[tuple[str, tuple[str, str]]],
    inlets: Collection[str] = (),
) -> list[tuple[str, tuple[str, str]]]:
    """Keep the signal positions worth showing or fitting, in the order given.

    Keeps the process outlets, the outlet port of each non-infrastructure unit, the
    column inlet, and the sources of the driven `inlets`.
    """
    return [
        (label, (unit, port))
        for label, (unit, port) in options
        if isinstance(units[unit], Outlet)
        or (isinstance(units[unit], Inlet) and unit in inlets)
        or (unit == "column" and port == "inlet")
        or (
            port == "outlet"
            and not isinstance(units[unit], Inlet)
            and unit not in _INFRASTRUCTURE_UNITS
        )
    ]


def measurable_signal_options(
    process: Any, options: Optional[Sequence[tuple[str, tuple[str, str]]]] = None
) -> list[tuple[str, tuple[str, str]]]:
    """Return plainly labelled, measurable `(label, (unit, port))` options of `process`.

    `options` defaults to `list_signal_ports(process)`; pass a result's
    `classify_signal_ports` list to restrict to recorded ports.
    """
    return friendly_signal_options(
        measurable_signal_ports(
            process.flow_sheet.units_dict,
            list_signal_ports(process) if options is None else options,
            active_inlets(process),
        )
    )


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
