"""Object widgets edit the given CADET-Process objects in place, stay in sync, and emit code."""
from __future__ import annotations

import numpy as np
import pytest
from cadetgui import (
    ComponentSystemWidget,
    FlowSheetWidget,
    ProcessWidget,
    SimulationWidget,
    UnitOperationsWidget,
)
from cadetgui.widgets.process_model import UnitOperationWidget
from cadetgui.widgets.process_model.values import MISSING_HTML
from CADETProcess.processModel import (
    ComponentSystem,
    FlowSheet,
    Inlet,
    Langmuir,
    LumpedRateModelWithoutPores,
    Outlet,
)

from .conftest import (
    COLUMN_VALUES,
    LRM,
    assert_same_flow_sheet,
    assert_same_units,
    create_units,
    event_list,
    outlet_solution,
)


def _units_dict(process):
    return {unit.name: unit for unit in process.flow_sheet.units}


CODE_CASES = {
    "ComponentSystemWidget": (
        lambda p: ComponentSystemWidget(p.component_system),
        lambda p: {},
        lambda p, ns: ns["component_system"].names == p.component_system.names,
    ),
    "UnitOperationsWidget": (
        lambda p: UnitOperationsWidget(p.component_system, _units_dict(p)),
        lambda p: {"component_system": p.component_system},
        lambda p, ns: all(assert_same_units(u, ns[u.name]) is None for u in p.flow_sheet.units),
    ),
    "FlowSheetWidget": (
        lambda p: FlowSheetWidget(p.flow_sheet, units=_units_dict(p)),
        lambda p: {"component_system": p.component_system, **_units_dict(p)},
        lambda p, ns: assert_same_flow_sheet(p.flow_sheet, ns["flow_sheet"]) is None,
    ),
    "ProcessWidget": (
        lambda p: ProcessWidget(p),
        lambda p: {"flow_sheet": p.flow_sheet},
        lambda p, ns: event_list(ns["process"]) == event_list(p),
    ),
    "SimulationWidget": (
        lambda p: SimulationWidget(p),
        lambda p: {"process": p},
        lambda p, ns: ns["simulation_results"].process is p,
    ),
}


@pytest.mark.parametrize("name", sorted(CODE_CASES))
def test_widget_code_rebuilds_an_equivalent_object(name, pulse_process):
    make, namespace, same = CODE_CASES[name]
    widget = make(pulse_process)
    ns = namespace(pulse_process)
    exec(widget.code(), ns)
    assert same(pulse_process, ns)


def test_chained_widget_code_reproduces_the_simulation(tracer):
    components, units, _flow_sheet = tracer
    for name, text in COLUMN_VALUES.items():
        units.parameter_picker.value = units.units["column"]
        units.editor.fields[f"column.{name}"].value = text
    units.parameter_picker.value = units.units["inlet"]
    units.editor.editors[0].fields[1].value = "0.005"
    units.editor.fields["inlet.flow_rate"].value = "1e-7"
    flow_sheet = FlowSheetWidget(
        FlowSheet(components.component_system, "flow_sheet"),
        units=units.units,
        connections=[("inlet", "column"), ("column", "outlet")],
    )
    process = ProcessWidget(flow_sheet.flow_sheet, name="tracer", values={"cycle_time": 600})

    namespace = {}
    exec("\n\n".join(w.code() for w in (components, units, flow_sheet, process)), namespace)
    np.testing.assert_allclose(
        outlet_solution(process.process), outlet_solution(namespace["process"])
    )


EDITS = {
    "ComponentSystemWidget": (
        lambda p: ComponentSystemWidget(p.component_system),
        lambda w: setattr(w.field, "value", ["A", "B"]),
        lambda p: p.component_system.names == ["A", "B"],
    ),
    "UnitOperationsWidget": (
        lambda p: UnitOperationsWidget(p.component_system, {"column": p.flow_sheet.column}),
        lambda w: setattr(w.editor.fields["column.total_porosity"], "value", "0.35"),
        lambda p: p.flow_sheet.column.total_porosity == 0.35,
    ),
    "FlowSheetWidget": (
        lambda p: FlowSheetWidget(p.flow_sheet, units=[*p.flow_sheet.units,
                                                      Outlet(p.component_system, "waste")]),
        lambda w: w.controls.add(),
        lambda p: "waste" in p.flow_sheet.units_dict,
    ),
    "ProcessWidget": (
        lambda p: ProcessWidget(p),
        lambda w: setattr(w.cycle_time, "value", "900"),
        lambda p: p.cycle_time == 900,
    ),
}


@pytest.mark.parametrize("name", sorted(EDITS))
def test_widget_edits_its_object_in_place_and_notifies(name, pulse_process):
    make, edit, edited = EDITS[name]
    widget = make(pulse_process)
    value = widget.get_value()
    seen = []
    widget.add_listener(seen.append)
    edit(widget)
    assert edited(pulse_process)
    assert len(seen) == 1
    assert widget.get_value() == value
    if not isinstance(value, dict):
        assert widget.get_value() is value


def test_widgets_of_one_model_follow_each_others_edits():
    component_system = ComponentSystem()
    components = ComponentSystemWidget(component_system)
    mirror = ComponentSystemWidget(component_system)
    units = {}
    unit_operations = UnitOperationsWidget(component_system, units)
    flow_sheet_widget = FlowSheetWidget(FlowSheet(component_system, "flow_sheet"), units=units)
    process_widget = ProcessWidget(flow_sheet_widget.flow_sheet)

    assert unit_operations.create() is None
    assert "Add a component first" in unit_operations.status.value
    components.field.value = ["Tracer"]
    assert mirror.field.value == ["Tracer"]

    create_units(unit_operations, ("Inlet", "inlet"), ("Outlet", "outlet"))
    controls = flow_sheet_widget.controls
    assert controls.unit_picker.option_labels == ["inlet", "outlet"]
    for unit in list(units.values()):
        controls.unit_picker.value = unit
        controls.add()
    controls.origin_picker.value = units["inlet"]
    controls.destination_picker.value = units["outlet"]
    controls.connect()
    assert "inlet · flow_rate" in process_widget.event_editor.path.option_labels

    unit_operations.parameter_picker.value = units["inlet"]
    unit_operations.editor.fields["inlet.flow_rate"].value = "1e-7"
    assert "missing parameter" not in flow_sheet_widget.diagram.value


def test_component_system_widget_creates_one_and_ignores_unnamed_rows():
    widget = ComponentSystemWidget()
    assert widget.component_system.n_comp == 0
    widget.field.value = ["", "Tracer", " "]
    assert widget.names == widget.component_system.names == ["Tracer"]


@pytest.mark.parametrize(
    "name, error",
    [("2column", "Use a name like"), ("class", "Use a name like"),
     ("column", "already a unit named"), ("column_2", None)],
)
def test_unit_operations_widget_checks_new_unit_names(tracer, name, error):
    _components, units, _flow_sheet = tracer
    unit = create_units(units, (LRM, name)).get(name) if error is None else None
    if error is None:
        assert isinstance(unit, LumpedRateModelWithoutPores)
        assert units.parameter_picker.value is unit
    else:
        units.name_field.value = name
        assert units.create() is None
        assert error in units.status.value


def test_unit_operations_widget_creates_given_model_classes_and_removes_units():
    units = UnitOperationsWidget(
        ComponentSystem(["A"]), {"inlet": Inlet, "column": LumpedRateModelWithoutPores}
    )
    assert isinstance(units.units["inlet"], Inlet)
    assert units.name_field.value == "inlet_2"
    units.remove("inlet")
    assert list(units.units) == ["column"]


@pytest.mark.parametrize(
    "text, error, stored",
    [("0.4", "", 0.4), ("1.5", "upper bound", None), ("abc", "Enter a number", None)],
)
def test_unit_parameters_are_edited_as_literals(tracer, text, error, stored):
    _components, units, _flow_sheet = tracer
    column = units.units["column"]
    units.parameter_picker.value = column
    field = units.editor.fields["column.total_porosity"]
    field.value = text
    assert error in field.error
    assert column.total_porosity == stored
    assert ("column.total_porosity = 0.4" in units.code()) == (stored is not None)


def test_unit_parameters_editor_reports_missing_parameters(tracer):
    _components, units, _flow_sheet = tracer
    column = units.units["column"]
    units.parameter_picker.value = column
    assert "Missing: axial_dispersion, diameter, length, total_porosity" in (
        units.editor.status.value
    )
    view = UnitOperationWidget(column)
    assert view._body.value.count(MISSING_HTML) == 4

    for name, text in COLUMN_VALUES.items():
        units.editor.fields[f"column.{name}"].value = text
    assert column.missing_parameters == []
    assert "All required parameters are set" in units.editor.status.value
    view.refresh()
    assert MISSING_HTML not in view._body.value


def test_unit_parameters_editor_edits_the_binding_model():
    component_system = ComponentSystem(["A"])
    column = LumpedRateModelWithoutPores(component_system, "column")
    column.binding_model = Langmuir(component_system, "langmuir")
    units = UnitOperationsWidget(component_system, {"column": column})
    units.editor.fields["column.binding_model.capacity"].value = "100"
    assert column.binding_model.capacity == [100]
    assert "column.binding_model.capacity = 100" in units.code()
    assert "Langmuir" in UnitOperationWidget(column)._body.value


def test_inlet_profiles_are_edited_by_their_coefficients(tracer):
    _components, units, _flow_sheet = tracer
    inlet = units.units["inlet"]
    units.parameter_picker.value = inlet
    [concentration] = units.editor.editors
    concentration.fields[1].value = "0.005"
    np.testing.assert_allclose(inlet.c[0], [0, 0.005, 0, 0])
    units.editor.fields["inlet.flow_rate"].value = "2e-7"
    assert inlet.flow_rate[0] == 2e-7

    profiled = UnitOperationsWidget(inlet.component_system, {"inlet": inlet},
                                    flow_rate_profile=True)
    assert len(profiled.editor.editors) == 2


def test_units_can_be_created_and_edited_in_separate_widgets():
    component_system = ComponentSystem(["Tracer"])
    units = {}
    creator = UnitOperationsWidget(component_system, units, edit=False)
    editor = UnitOperationsWidget(component_system, units, create=False)
    create_units(creator, (LRM, "column"))
    assert editor.parameter_picker.value is units["column"]
    editor.editor.fields["column.length"].value = "0.1"
    assert units["column"].length == 0.1


def test_flow_sheet_build_controls_add_connect_and_remove(tracer):
    _components, units, widget = tracer
    flow_sheet, controls = widget.flow_sheet, widget.controls
    inlet, column, outlet = (units.units[n] for n in ("inlet", "column", "outlet"))
    for unit in (inlet, column, outlet):
        controls.unit_picker.value = unit
        controls.add()
    assert controls.unit_picker.option_labels == []
    for origin, destination in ((inlet, outlet), (inlet, column)):
        controls.origin_picker.value, controls.destination_picker.value = origin, destination
        controls.connect()
    assert flow_sheet.connection_exists(inlet, outlet)
    assert "flow_sheet.add_connection(inlet, column)" in widget.code()

    controls.connect()
    assert controls.status.value

    def remove(label):
        row = next(r for r in controls._added.children if label in r.children[1].value)
        row.children[0].click()

    remove("inlet → outlet")
    assert not flow_sheet.connection_exists(inlet, outlet)
    assert flow_sheet.connection_exists(inlet, column)
    remove(">column</code>")
    assert column not in flow_sheet.units
    assert controls.unit_picker.option_labels == ["column"]


def test_flow_sheet_widget_follows_units_added_in_code():
    component_system = ComponentSystem(1)
    flow_sheet = FlowSheet(component_system, "flow_sheet")
    widget = FlowSheetWidget(flow_sheet)
    assert widget.unit_view is None
    column = LumpedRateModelWithoutPores(component_system, "column")
    flow_sheet.add_unit(Inlet(component_system, "inlet"))
    flow_sheet.add_unit(column)
    widget.refresh()
    assert widget.unit_picker.option_labels == ["inlet", "column"]
    assert widget.unit_view.unit is column
