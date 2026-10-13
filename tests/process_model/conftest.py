"""Fixtures for the process-model object widgets: small models and equivalence checks."""
from __future__ import annotations

import matplotlib
import numpy as np
import pytest
from CADETProcess.processModel import (
    ComponentSystem,
    LumpedRateModelWithoutPores,
    Process,
)

matplotlib.use("Agg")

LRM = "Lumped Rate Model Without Pores (LRM)"
COLUMN_VALUES = {"length": "0.1", "diameter": "0.02", "total_porosity": "0.4",
                 "axial_dispersion": "1e-7"}


def create_units(widget, *models):
    """Create `(model label, name)` units with a UnitOperationsWidget's controls."""
    for label, name in models:
        widget.model_picker.selected_index = widget.model_picker.option_labels.index(label)
        widget.name_field.value = name
        widget.create()
    return widget.units


@pytest.fixture
def tracer():
    """Component, unit-operation and flow-sheet widgets on one empty 'Tracer' model."""
    from cadetgui import ComponentSystemWidget, FlowSheetWidget, UnitOperationsWidget
    from CADETProcess.processModel import FlowSheet

    components = ComponentSystemWidget(ComponentSystem(["Tracer"]))
    units = UnitOperationsWidget(components.component_system)
    create_units(units, ("Inlet", "inlet"), (LRM, "column"), ("Outlet", "outlet"))
    flow_sheet = FlowSheetWidget(
        FlowSheet(components.component_system, "flow_sheet"), units=units.units
    )
    return components, units, flow_sheet


@pytest.fixture
def lc_process():
    """A Process on a two-component LCFlowSheet, so process templates apply."""
    from CADETProcess.instruments import LCFlowSheet

    flow_sheet = LCFlowSheet(
        ComponentSystem(["Salt", "A"]), sample_loop_volume=50e-9,
        ColumnModel=LumpedRateModelWithoutPores,
    )
    flow_sheet.mixer.init_liquid_volume = 1e-7
    for name in ("tubing_pre_injection", "tubing_pre_column", "tubing_post_column",
                 "tubing_detectors"):
        tubing = getattr(flow_sheet, name)
        tubing.length, tubing.diameter, tubing.axial_dispersion = 0.1, 5e-4, 1e-6
    column = flow_sheet.column
    column.length, column.diameter = 0.1, 0.01
    column.total_porosity, column.axial_dispersion = 0.4, 1e-7
    return Process(flow_sheet, "process")


def event_list(process):
    """Cycle time and events of a process as comparable plain values."""
    return float(process.cycle_time), sorted(
        (e.name, e.parameter_path, np.ravel(e.full_state).tolist(), float(e.time))
        for e in process.events
    )


def assert_same_units(built, rebuilt):
    """Assert two units have the same model, required parameters and inlet profiles."""
    assert type(built) is type(rebuilt) and built.name == rebuilt.name
    names = list(built.required_parameters) + list(getattr(built, "polynomial_parameters", {}))
    for name in names:
        np.testing.assert_allclose(getattr(built, name), getattr(rebuilt, name))


def assert_same_flow_sheet(built, rebuilt):
    """Assert two flow sheets have the same units, parameters and connections."""
    assert [u.name for u in built.units] == [u.name for u in rebuilt.units]
    for unit in built.units:
        assert_same_units(unit, rebuilt[unit.name])
    from cadetgui.widgets.diagrams.flow_sheet import flow_sheet_edges

    def edges(flow_sheet):
        return sorted((o.name, d.name) for o, d in flow_sheet_edges(flow_sheet))

    assert edges(built) == edges(rebuilt)


def outlet_solution(process):
    """Simulate `process` and return the solution at its outlet."""
    from cadetgui.process_model.simulation import run_process

    return run_process(process).solution.outlet.outlet.solution
