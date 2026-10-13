"""Process templates of `CADETProcess.instruments` as ModelSpecs, and their phases."""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from CADETProcess.instruments import (
    LWE,
    Breakthrough,
    LCFlowSheet,
    PulseInjection,
    Step,
    StepElution,
)
from CADETProcess.processModel import (
    ComponentSystem,
    FlowSheet,
    Inlet,
    Outlet,
    Process,
)

from ..parameters.specs import FieldSpec, ModelSpec, parse_float_list, require_positive

CONCENTRATION_UNITS = r"\frac{\mathrm{mol}}{\mathrm{m}^{3}_{\mathrm{IV}}}"

# 1 mL/min in m^3/s, written at the 10 significant figures the event sliders round to.
DEFAULT_FLOW_RATE = 1.666666667e-8

# Shared scalar process fields (m^3/s, s). Per-component concentration fields are built
# by `_concentration_field` instead, since they depend on the component system.
PARAMS: dict[str, FieldSpec] = {
    "flow_rate": FieldSpec(
        "flow_rate", "float", "Flow rate", DEFAULT_FLOW_RATE,
        validate=require_positive, units=r"\frac{\mathrm{m}^{3}}{\mathrm{s}}",
    ),
    "flow_rate_wash": FieldSpec(
        "flow_rate_wash", "float", "Flow rate", DEFAULT_FLOW_RATE,
        validate=require_positive, units=r"\frac{\mathrm{m}^{3}}{\mathrm{s}}",
    ),
    "cycle_time": FieldSpec(
        "cycle_time", "float", "Cycle time", 600.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "pulse_duration": FieldSpec(
        "pulse_duration", "float", "Pulse duration", 10.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_wash": FieldSpec(
        "delta_t_wash", "float", "Wash duration", 300.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_elute": FieldSpec(
        "delta_t_elute", "float", "Elution duration", 900.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
    "delta_t_final_wash": FieldSpec(
        "delta_t_final_wash", "float", "Final wash duration", 300.0,
        validate=require_positive, units=r"\mathrm{s}",
    ),
}


def _pick(keys: Sequence[str]) -> list[FieldSpec]:
    return [PARAMS[k] for k in keys]


def _concentration_field(
    name: str,
    label: str,
    default_scalar: float,
    component_system: ComponentSystem,
    default_others: Optional[float] = None,
) -> FieldSpec:
    """Return a per-component concentration field sized from `component_system`.

    With `default_others`, the first component (the salt) defaults to `default_scalar`
    and every further one to `default_others`.
    """
    names = tuple(component_system.names)
    n_comp = len(names) or 1
    others = default_scalar if default_others is None else default_others
    return FieldSpec(
        name, "float_list", label, [default_scalar] + [others] * (n_comp - 1),
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
        # The first component is the gradient's salt; the others are only in the sample.
        _concentration_field("c_buffer_a", "Buffer A concentration", 20.0, cs, 0.0),
        _concentration_field("c_buffer_b", "Buffer B concentration", 1000.0, cs, 0.0),
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
