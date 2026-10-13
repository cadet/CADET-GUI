"""Signal positions of an LC process, in plain names, and those worth measuring."""

from __future__ import annotations

from typing import Any, Collection, Mapping, Optional, Sequence

from CADETProcess.processModel import Inlet, Outlet

from ..process_model.signals import list_signal_ports
from .system import INLET_UNITS, UNIT_LABELS, active_inlets


def signal_label(unit: str, port: str) -> str:
    """Plain-language name of a signal position, e.g. "Column outlet" or "Outlet"."""
    name = UNIT_LABELS.get(unit, unit.replace("_", " ").capitalize())
    if unit in ("outlet", "waste"):
        return name
    if port == "outlet" and unit in INLET_UNITS:
        return f"{name} inlet"
    return f"{name} {port}"


def friendly_signal_options(
    options: Sequence[tuple[str, tuple[str, str]]],
) -> list[tuple[str, tuple[str, str]]]:
    """Relabel `(label, (unit, port))` signal options with `signal_label`."""
    return [(signal_label(unit, port), (unit, port)) for _, (unit, port) in options]


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
