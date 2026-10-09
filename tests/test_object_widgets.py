from __future__ import annotations

import warnings

import pytest
from cadetgui import EventsWidget, FlowSheetWidget, ParametersWidget, SimulationWidget
from cadetgui.widgets.composite.flow_sheet_widget import render_flow_sheet_svg
from CADETProcess.processModel import (
    ComponentSystem,
    Cstr,
    FlowSheet,
    Inlet,
    Langmuir,
    LumpedRateModelWithoutPores,
    Outlet,
    Process,
)

warnings.filterwarnings("ignore", category=UserWarning)


def _flow_sheet(*units, connections=None):
    flow_sheet = FlowSheet(units[0].component_system, "flow_sheet")
    for unit in units:
        flow_sheet.add_unit(unit)
    for origin, destination in connections or zip(units, units[1:]):
        flow_sheet.add_connection(origin, destination)
    return flow_sheet


@pytest.fixture
def process():
    cs = ComponentSystem(["A"])
    inlet = Inlet(cs, "inlet")
    inlet.c = 1
    inlet.flow_rate = 1e-7
    column = LumpedRateModelWithoutPores(cs, "column")
    column.length = 0.1
    column.diameter = 0.02
    column.total_porosity = 0.4
    column.axial_dispersion = 1e-7
    process = Process(_flow_sheet(inlet, column, Outlet(cs, "outlet")), "process")
    process.cycle_time = 600
    return process


def test_parameters_widget_shows_unset_parameters_as_missing():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = ParametersWidget(column)

    assert widget.fields["length"].value == ""
    assert "length" in widget._missing.value
    assert column.missing_parameters


def test_parameters_widget_writes_edits_into_the_object():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = ParametersWidget(column)
    seen = []
    widget.add_listener(seen.append)

    for name, text in {
        "length": "0.1", "diameter": "0.02", "total_porosity": "0.4", "axial_dispersion": "1e-7"
    }.items():
        widget.fields[name].value = text

    assert column.length == 0.1
    assert column.missing_parameters == []
    assert "All required parameters are set" in widget._missing.value
    assert seen[-1] is column


def test_parameters_widget_shows_cadet_process_validation_errors():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = ParametersWidget(column)

    widget.fields["total_porosity"].value = "1.5"
    assert "upper bound" in widget.fields["total_porosity"].error
    assert column.total_porosity is None

    widget.fields["length"].value = "ten"
    assert "Enter a number" in widget.fields["length"].error


def test_parameters_widget_shows_constant_inlet_profiles_as_plain_values():
    inlet = Inlet(ComponentSystem(2), "inlet")
    widget = ParametersWidget(inlet)

    widget.fields["c"].value = "[1, 2]"
    widget.fields["flow_rate"].value = "1e-7"

    assert widget.fields["c"].value == "[1.0, 2.0]"
    assert widget.fields["flow_rate"].value == "1e-07"
    assert inlet.c[:, 0].tolist() == [1.0, 2.0]


def test_parameters_widget_refresh_follows_changes_made_in_code():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = ParametersWidget(column)
    column.length = 0.25
    widget.refresh()
    assert widget.fields["length"].value == "0.25"


def test_flow_sheet_diagram_draws_every_unit_and_connection(process):
    svg = render_flow_sheet_svg(process.flow_sheet)
    for name in ("inlet", "column", "outlet", "LumpedRateModelWithoutPores"):
        assert f">{name}<" in svg
    assert svg.count('marker-end="url(#cg-arrow)"') == 2


def test_flow_sheet_diagram_handles_a_recycle_loop():
    cs = ComponentSystem(1)
    inlet, cstr, column, outlet = (
        Inlet(cs, "inlet"), Cstr(cs, "cstr"),
        LumpedRateModelWithoutPores(cs, "column"), Outlet(cs, "outlet"),
    )
    flow_sheet = _flow_sheet(
        inlet, cstr, column, outlet,
        connections=[(inlet, cstr), (cstr, column), (column, outlet), (column, cstr)],
    )
    svg = render_flow_sheet_svg(flow_sheet)
    assert svg.count('marker-end="url(#cg-arrow)"') == 4
    assert ">CSTR<" in svg


def test_flow_sheet_widget_refresh_shows_units_added_later():
    cs = ComponentSystem(1)
    flow_sheet = FlowSheet(cs, "flow_sheet")
    widget = FlowSheetWidget(flow_sheet)
    assert "no units yet" in widget.diagram.value
    assert widget.unit_picker.layout.display == "none"

    flow_sheet.add_unit(Inlet(cs, "inlet"))
    widget.refresh()
    assert ">inlet<" in widget.diagram.value
    assert widget.unit_picker.option_labels == ["inlet"]


def test_flow_sheet_widget_marks_and_selects_units_with_missing_parameters():
    cs = ComponentSystem(1)
    column = LumpedRateModelWithoutPores(cs, "column")
    widget = FlowSheetWidget(_flow_sheet(Inlet(cs, "inlet"), column, Outlet(cs, "outlet")))

    assert widget.unit_picker.value is column
    assert "4 missing parameters" in widget.diagram.value

    widget.parameters[0].fields["length"].value = "0.1"
    assert "3 missing parameters" in widget.diagram.value


def test_flow_sheet_widget_shows_a_columns_binding_model():
    cs = ComponentSystem(1)
    column = LumpedRateModelWithoutPores(cs, "column")
    widget = FlowSheetWidget(_flow_sheet(Inlet(cs, "inlet"), column, Outlet(cs, "outlet")))
    assert [type(p.obj).__name__ for p in widget.parameters] == ["LumpedRateModelWithoutPores"]

    column.binding_model = Langmuir(cs, "langmuir")
    widget.refresh()
    assert [p.obj for p in widget.parameters] == [column, column.binding_model]


def test_events_widget_lists_events_and_their_timelines(process):
    widget = EventsWidget(process)
    assert "no events" in widget._table.value

    process.add_event("wash", "flow_sheet.inlet.c", 0, 300)
    widget.refresh()
    assert "flow_sheet.inlet.c" in widget._table.value
    assert [s["name"] for s in widget.chart.series] == ["Inlet"]


def test_simulation_widget_runs_and_plots_the_outlet_first(process):
    widget = SimulationWidget(process)
    seen = []
    widget.add_listener(seen.append)

    results = widget.run()

    assert results is widget.get_value() is seen[0]
    assert widget._signal.option_labels[0] == "Outlet"
    assert widget.chart.series[0]["name"] == "A"


def test_simulation_widget_reports_a_failed_run(process):
    process.flow_sheet.column.length = None
    widget = SimulationWidget(process)
    assert widget.run() is None
    assert "Simulation failed" in widget.status.value


def test_simulation_widget_overlays_a_reference(process):
    import numpy as np
    from CADETProcess.reference import ReferenceIO

    time = np.linspace(0, 600, 61)
    reference = ReferenceIO("measured", time, (time > 120).astype(float))
    widget = SimulationWidget(process, reference=reference)
    assert [s["name"] for s in widget.chart.series] == ["measured"]

    widget.run()
    assert [s["name"] for s in widget.chart.series] == ["A", "measured"]
    assert widget.chart.series[1]["dashed"]
