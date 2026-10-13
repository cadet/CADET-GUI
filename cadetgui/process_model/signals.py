"""The `(unit, port)` positions of a process whose solution can be shown."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from CADETProcess.processModel import Inlet, Outlet

__all__ = ["classify_signal_ports", "list_signal_ports", "signal_positions"]


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


def signal_positions(
    units: Mapping[str, Any], ports_by_unit: Mapping[str, Sequence[str]]
) -> list[tuple[str, str]]:
    """List the `(unit, port)` positions with a meaningful solution, in the given order.

    An Inlet is read at its outlet and an Outlet at its inlet (their other ports are
    bookkeeping); every port of other units is kept.
    """
    positions = []
    for unit_name, ports in ports_by_unit.items():
        unit = units.get(unit_name)
        only = (
            "outlet" if isinstance(unit, Inlet) else "inlet" if isinstance(unit, Outlet) else None
        )
        positions += [(unit_name, port) for port in ports if only in (None, port)]
    return positions


def _order_signal_ports(
    units: Mapping[str, Any], ports_by_unit: Mapping[str, Sequence[str]]
) -> list[tuple[str, tuple[str, str]]]:
    sinks: list[tuple[str, str, tuple[str, str]]] = []
    others: list[tuple[str, tuple[str, str]]] = []
    for unit_name, port in signal_positions(units, ports_by_unit):
        unit = units.get(unit_name)
        if isinstance(unit, Inlet):
            others.append((f"{unit_name}: Source", (unit_name, port)))
        elif isinstance(unit, Outlet):
            sinks.append((unit_name, f"{unit_name}: Sink", (unit_name, port)))
        else:
            others.append((f"{unit_name}: {port}", (unit_name, port)))
    sinks.sort(key=lambda entry: entry[0] != "outlet")
    return [(label, value) for _, label, value in sinks] + others
