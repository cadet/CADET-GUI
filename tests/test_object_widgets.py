from __future__ import annotations

import warnings

import numpy as np
import pytest
from cadetgui import FlowSheetWidget, ProcessWidget, SimulationWidget
from cadetgui.widgets._units import unit_html
from cadetgui.widgets.composite import UnitOperationWidget
from cadetgui.widgets.composite._parameter_values import (
    assign_literal,
    format_value,
    value_html,
)
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


def test_flow_sheet_and_process_widgets_name_the_components(process):
    assert "Components: A" in FlowSheetWidget(process.flow_sheet)._components.value
    assert "Components: A" in ProcessWidget(process).root.children[2].value


def test_unit_operation_widget_marks_missing_parameters_and_shows_units():
    column = LumpedRateModelWithoutPores(ComponentSystem(1), "column")
    widget = UnitOperationWidget(column)
    assert widget._body.value.count(">missing</span>") == 4

    column.length = 0.1
    column.axial_dispersion = 1e-7
    widget.refresh()
    assert widget._body.value.count(">missing</span>") == 2
    assert "0.1 <span class='cadetgui-param-unit'>m</span>" in widget._body.value
    assert "10<sup>−7</sup> <span class='cadetgui-param-unit'>m<sup>2</sup><sub>IV</sub>/s" in (
        widget._body.value
    )


def test_unit_operation_widget_shows_the_binding_model():
    cs = ComponentSystem(1)
    column = LumpedRateModelWithoutPores(cs, "column")
    assert "Binding model: none" in UnitOperationWidget(column)._body.value
    assert "Binding model" not in UnitOperationWidget(Inlet(cs, "inlet"))._body.value

    column.binding_model = Langmuir(cs, "langmuir")
    body = UnitOperationWidget(column)._body.value
    assert "Binding model: Langmuir" in body and "capacity" in body


def test_values_read_without_brackets_and_per_component():
    cs = ComponentSystem(["Salt", "Protein"])
    binding = Langmuir(cs, "langmuir")
    binding.capacity = [0, 100]
    binding.adsorption_rate = [2.5e-5, 2.5e-5]

    assert value_html(binding, "capacity") == "Salt: 0, Protein: 100"
    assert value_html(binding, "adsorption_rate") == "2.5 × 10<sup>−5</sup>"
    assert format_value(binding, "capacity") == "0, 100"
    assert format_value(binding, "adsorption_rate") == "2.5e-5"
    assert assign_literal(binding, "capacity", "10, 20") is None
    assert binding.capacity == [10, 20]


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
    assert {"cycle_time", "flow_sheet.column.length"} <= set(widget.fields)

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
    assert [editor.name for editor in widget.editors] == ["flow_rate"]
    assert "flow_sheet.inlet.c" in widget._events_table.value
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
    time = np.linspace(0, 600, 61)
    reference = ReferenceIO("measured", time, (time > 120).astype(float))
    widget = SimulationWidget(process, reference=reference)
    assert [s["name"] for s in widget.chart.series] == ["measured"]

    widget.run()
    assert [s["name"] for s in widget.chart.series] == ["A", "measured"]
    assert widget.chart.series[1]["dashed"]


def test_process_widget_edits_inlet_profiles_as_polynomials(process):
    widget = ProcessWidget(process)
    concentration, flow_rate = widget.editors
    assert concentration.chart.points == [1.0, 1.0, 1.0, 1.0]
    assert "flow_sheet.inlet.c" not in widget.fields

    concentration.chart.points = [0.0, 1.0, 2.0, 3.0]
    np.testing.assert_allclose(process.flow_sheet.inlet.c[0], [0, 3 / 600, 0, 0], atol=1e-12)
    assert concentration.fields[1].value == "0.005"

    flow_rate.fields[0].value = "2e-7"
    assert process.flow_sheet.inlet.flow_rate[0] == 2e-7


def test_polynomial_editor_restarts_the_profile_in_every_section(process):
    process.flow_sheet.inlet.c = [[0, 0.01, 0, 0]]
    process.add_event("flow", "flow_sheet.inlet.flow_rate", 1e-7, 300)
    editor = ProcessWidget(process).editors[0]

    assert editor.chart.duration == 300
    curve = editor.chart.curve
    assert max(curve["values"]) == pytest.approx(3.0)
    assert curve["values"][curve["times"].index(300.0)] == pytest.approx(3.0)


def test_builders_create_a_model_that_their_code_reproduces():
    from cadetgui import ComponentSystemWidget, UnitOperationsWidget
    from CADETProcess.simulator import Cadet

    components = ComponentSystemWidget(names=["Tracer"])
    component_system = components.component_system
    assert components.component_system is component_system

    units = UnitOperationsWidget(component_system)
    for label, name in [
        ("Inlet", "inlet"),
        ("Lumped Rate Model Without Pores (LRM)", "column"),
        ("Outlet", "outlet"),
    ]:
        units.model_picker.selected_index = units.model_picker.option_labels.index(label)
        units.name_field.value = name
        units.create()

    flow_sheet = FlowSheet(component_system, "flow_sheet")
    flow_sheet_widget = FlowSheetWidget(flow_sheet, units=units)
    controls = flow_sheet_widget.controls
    for _ in range(3):
        controls.add()
    for origin, destination in [("inlet", "column"), ("column", "outlet")]:
        controls.origin_picker.value = units.units[origin]
        controls.destination_picker.value = units.units[destination]
        controls.connect()
    assert "missing parameter" in flow_sheet_widget.diagram.value

    process_widget = ProcessWidget(flow_sheet, name="tracer")
    process_widget.fields["cycle_time"].value = "600"
    for name, text in {
        "length": "0.1", "diameter": "0.02", "total_porosity": "0.4", "axial_dispersion": "1e-7",
    }.items():
        process_widget.fields[f"flow_sheet.column.{name}"].value = text
    concentration, flow_rate = process_widget.editors
    concentration.chart.points = [0.0, 1.0, 2.0, 3.0]
    flow_rate.fields[0].value = "1e-7"

    code = "\n\n".join(
        widget.code() for widget in (components, units, flow_sheet_widget, process_widget)
    )
    namespace = {}
    exec(code, namespace)

    simulator = Cadet()
    built = simulator.simulate(process_widget.process).solution.outlet.outlet.solution
    rebuilt = simulator.simulate(namespace["process"]).solution.outlet.outlet.solution
    np.testing.assert_allclose(built, rebuilt)


def test_component_system_widget_replaces_the_object_only_when_names_change():
    from cadetgui import ComponentSystemWidget

    widget = ComponentSystemWidget(names=["Tracer"])
    first = widget.component_system
    assert widget.get_value() is first

    widget.field.value = ["Salt", "Protein"]
    assert widget.component_system is not first
    assert widget.component_system.names == ["Salt", "Protein"]
    assert 'ComponentSystem(["Salt", "Protein"])' in widget.code()


def test_builders_start_from_presets():
    from cadetgui import ComponentSystemWidget, UnitOperationsWidget

    components = ComponentSystemWidget(names=["Tracer"])
    units = UnitOperationsWidget(
        components.component_system,
        units={"inlet": Inlet, "column": LumpedRateModelWithoutPores, "outlet": Outlet},
    )
    assert list(units.units) == ["inlet", "column", "outlet"]
    assert 'column = LumpedRateModelWithoutPores(component_system, "column")' in units.code()

    flow_sheet_widget = FlowSheetWidget(
        FlowSheet(components.component_system, "flow_sheet"),
        units=units,
        connections=[("inlet", "column"), ("column", "outlet")],
    )
    assert "flow_sheet.add_connection(column, outlet)" in flow_sheet_widget.code()

    process_widget = ProcessWidget(
        flow_sheet_widget.flow_sheet,
        name="tracer",
        values={
            "cycle_time": 600,
            "flow_sheet.inlet.c": 1,
            "flow_sheet.inlet.flow_rate": 1e-7,
            "flow_sheet.column.length": 0.1,
            "flow_sheet.column.diameter": 0.02,
            "flow_sheet.column.total_porosity": 0.4,
            "flow_sheet.column.axial_dispersion": 1e-7,
        },
    )
    process = process_widget.process
    assert process.cycle_time == 600
    assert process.flow_sheet.column.missing_parameters == []
    assert "column.total_porosity = 0.4" in process_widget.code()


def test_component_system_widget_starts_empty_and_ignores_unnamed_rows():
    from cadetgui import ComponentSystemWidget

    widget = ComponentSystemWidget()
    assert widget.field.value == []
    assert widget.component_system.n_comp == 0

    widget.field.value = ["", "Tracer", " "]
    assert widget.names == ["Tracer"]
    assert 'ComponentSystem(["Tracer"])' in widget.code()


def test_unit_operations_widget_follows_the_component_system_widget():
    from cadetgui import ComponentSystemWidget, UnitOperationsWidget

    components = ComponentSystemWidget()
    units = UnitOperationsWidget(components)
    assert units.create() is None
    assert "Add a component first" in units.status.value

    components.field.value = ["Tracer"]
    inlet = units.create()
    assert inlet.component_system is components.component_system
    assert "No parameters" not in UnitOperationWidget(inlet)._body.value


def test_parameter_view_handles_units_without_components():
    inlet = Inlet(ComponentSystem(0), "inlet")
    assert "Concentration" in UnitOperationWidget(inlet)._body.value
