from __future__ import annotations

import warnings

import numpy as np
import pytest
from cadetgui import (
    ComponentSystemWidget,
    FlowSheetWidget,
    ProcessWidget,
    SimulationWidget,
    UnitOperationWidget,
)
from cadetgui.widgets._units import unit_html
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
from CADETProcess.reference import ReferenceIO

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


def test_unit_html_renders_cadet_process_units():
    assert unit_html(r"\frac{\mathrm{m}^{2}_{\mathrm{IV}}}{\mathrm{s}}") == (
        "m<sup>2</sup><sub>IV</sub>/s"
    )
    assert unit_html(r"\frac{\mathrm{m}^{3}}{\mathrm{mol}\cdot\mathrm{s}}") == (
        "m<sup>3</sup>/(mol·s)"
    )


def test_component_system_widget_lists_components():
    widget = ComponentSystemWidget(ComponentSystem(["Salt", "Protein"]))
    assert "2 components" in widget._body.value
    assert "<td>Protein</td>" in widget._body.value


def test_unit_operation_widget_marks_missing_parameters_and_shows_units():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = UnitOperationWidget(column)
    assert widget._body.value.count("missing</span>") == 4
    assert "m<sup>2</sup><sub>IV</sub>/s" in widget._body.value

    column.length = 0.1
    widget.refresh()
    assert widget._body.value.count("missing</span>") == 3
    assert "<code>0.1</code>" in widget._body.value


def test_unit_operation_widget_shows_the_binding_model():
    cs = ComponentSystem(1)
    column = LumpedRateModelWithoutPores(cs, "column")
    assert "NoBinding" in UnitOperationWidget(column)._body.value

    column.binding_model = Langmuir(cs, "langmuir")
    body = UnitOperationWidget(column)._body.value
    assert "Langmuir" in body and "capacity" in body


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


def test_flow_sheet_widget_marks_and_shows_units_with_missing_parameters():
    cs = ComponentSystem(1)
    column = LumpedRateModelWithoutPores(cs, "column")
    widget = FlowSheetWidget(_flow_sheet(Inlet(cs, "inlet"), column, Outlet(cs, "outlet")))

    assert "4 missing parameters" in widget.diagram.value
    assert widget.unit_view.unit is column


def test_process_widget_edits_parameters_by_path(process):
    widget = ProcessWidget(process)
    seen = []
    widget.add_listener(seen.append)
    assert {"cycle_time", "flow_sheet.inlet.flow_rate", "flow_sheet.column.length"} <= set(
        widget.fields
    )

    widget.fields["flow_sheet.column.total_porosity"].value = "0.3"
    widget.fields["cycle_time"].value = "900"

    assert process.flow_sheet.column.total_porosity == 0.3
    assert process.cycle_time == 900
    assert seen == [process, process]


def test_process_widget_shows_cadet_process_validation_errors(process):
    widget = ProcessWidget(process)
    field = widget.fields["flow_sheet.column.total_porosity"]

    field.value = "1.5"
    assert "upper bound" in field.error
    assert process.flow_sheet.column.total_porosity == 0.4

    field.value = "ten"
    assert "Enter a number" in field.error


def test_process_widget_locks_parameters_set_by_events(process):
    process.add_event("wash", "flow_sheet.inlet.c", 0, 300)
    widget = ProcessWidget(process)

    assert widget.fields["flow_sheet.inlet.c"].disabled
    assert not widget.fields["flow_sheet.inlet.flow_rate"].disabled
    assert "flow_sheet.inlet.c" in widget._events_table.value
    assert [s["name"] for s in widget.chart.series] == ["Inlet"]


def test_process_widget_shows_constant_inlet_profiles_as_plain_values(process):
    widget = ProcessWidget(process)
    assert widget.fields["flow_sheet.inlet.c"].value == "[1.0]"
    assert widget.fields["flow_sheet.inlet.flow_rate"].value == "1e-07"


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
    time = np.linspace(0, 600, 61)
    reference = ReferenceIO("measured", time, (time > 120).astype(float))
    widget = SimulationWidget(process, reference=reference)
    assert [s["name"] for s in widget.chart.series] == ["measured"]

    widget.run()
    assert [s["name"] for s in widget.chart.series] == ["A", "measured"]
    assert widget.chart.series[1]["dashed"]
