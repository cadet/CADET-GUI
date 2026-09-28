from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from CADETProcess.instruments import LCFlowSheet
from CADETProcess.processModel import ComponentSystem

from ...cadetprocessadapter import BYPASSABLE_UNITS
from ...configuration_store import InstrumentState


def _import_line(obj: Any) -> str:
    cls = obj if isinstance(obj, type) else type(obj)
    return f"from {cls.__module__} import {cls.__name__}"


def instrument_script(
    *,
    process: Any,
    flow_sheet: LCFlowSheet,
    state: InstrumentState,
    column: Optional[Any],
    binding_model: Optional[Any],
    component_names: Sequence[str],
    column_values: Mapping[str, Any],
    binding_values: Mapping[str, Any],
    model_values: Mapping[str, Any],
) -> str:
    """Generate a script that rebuilds `process` around an `LCFlowSheet`."""
    proc_cls = type(process)
    imports = [_import_line(ComponentSystem), _import_line(LCFlowSheet)]
    if column is not None:
        imports.append(_import_line(column))
    if binding_model is not None:
        imports.append(_import_line(binding_model))
    imports.append(_import_line(proc_cls))

    kwargs = ["component_system"]
    if state.include_sample_loop:
        kwargs.append(f"sample_loop_volume={state.sample_loop_volume!r}")
        if not state.sample_loop_diameter_auto:
            kwargs.append(f"sample_loop_diameter={state.sample_loop_diameter!r}")
    if column is not None:
        kwargs.append(f"ColumnModel={type(column).__name__}")
    if binding_model is not None:
        kwargs.append(f"BindingModel={type(binding_model).__name__}")
    if state.bypass_units:
        kwargs.append(f"bypass_units={state.bypass_units!r}")

    lines = [
        "",
        f"component_system = ComponentSystem({list(component_names)!r})",
        "",
        "flow_sheet = LCFlowSheet(" + ", ".join(kwargs) + ")",
    ]

    # Mixer/tubing geometry has no parameter form, so its live values are emitted directly.
    for unit_name in BYPASSABLE_UNITS:
        unit = getattr(flow_sheet, unit_name, None) if unit_name != "column" else None
        if unit is None:
            continue
        lines.append("")
        lines.extend(
            f"flow_sheet.{unit_name}.{p} = {getattr(unit, p)!r}" for p in unit.required_parameters
        )

    if column is not None:
        lines.append("")
        lines.extend(f"flow_sheet.column.{k} = {v!r}" for k, v in column_values.items())
    if binding_model is not None:
        lines.append("")
        lines.extend(
            f"flow_sheet.column.binding_model.{k} = {v!r}" for k, v in binding_values.items()
        )

    lines.append("")
    lines.append(f"process = {proc_cls.__name__}({process.name!r}, flow_sheet,")
    lines.extend(f"    {k}={v!r}," for k, v in model_values.items())
    lines.append(")")
    return "\n".join(imports + lines)


def standalone_script(
    *,
    process: Any,
    column: Any,
    binding_model: Optional[Any],
    component_names: Sequence[str],
    column_values: Mapping[str, Any],
    binding_values: Mapping[str, Any],
    model_values: Mapping[str, Any],
    export: Callable[[Mapping[str, Any]], list[str]],
) -> str:
    """Generate a script that rebuilds `process` around a bare column; `export` emits the tail."""
    col_cls = type(column)
    imports = [
        _import_line(ComponentSystem),
        "from CADETProcess.processModel import FlowSheet, Inlet, Outlet",
        _import_line(col_cls),
    ]
    if binding_model is not None:
        imports.append(_import_line(binding_model))
    imports.append(_import_line(process))

    lines = [
        "",
        f"component_system = ComponentSystem({list(component_names)!r})",
        "",
        f"column = {col_cls.__name__}(component_system, name='column')",
    ]
    lines.extend(f"column.{k} = {v!r}" for k, v in column_values.items())
    if binding_model is not None:
        lines.append(
            f"column.binding_model = {type(binding_model).__name__}("
            "component_system, name='binding_model')"
        )
        lines.extend(f"column.binding_model.{k} = {v!r}" for k, v in binding_values.items())
    lines.extend(export(model_values))
    return "\n".join(imports + lines)
