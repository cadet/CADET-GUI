"""The `(unit, port)` positions of a process whose solution can be shown."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from CADETProcess.processModel import Inlet, Outlet


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
