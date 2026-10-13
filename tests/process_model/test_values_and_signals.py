"""Headless helpers: parameter values as text, parameter paths, signal positions, time grid."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.process_model.signals import classify_signal_ports, list_signal_ports
from cadetgui.process_model.simulation import Simulator, output_time_step
from cadetgui.process_model.values import (
    assign_literal,
    code_literal,
    format_value,
    has_parameter,
    number_text,
    parameter_names,
    parameter_owners,
    plain_value,
    resolve_path,
    set_by_path,
)
from cadetgui.widgets.process_model.values import value_html
from cadetgui.widgets.ui.format import unit_html
from CADETProcess.processModel import (
    ComponentSystem,
    Inlet,
    Langmuir,
    LumpedRateModelWithoutPores,
    Outlet,
)

CS = ComponentSystem(["Salt", "Protein"])


def _owner(kind, **values):
    obj = {"langmuir": Langmuir, "inlet": Inlet, "column": LumpedRateModelWithoutPores}[kind](
        CS, kind
    )
    for name, value in values.items():
        setattr(obj, name, value)
    return obj


@pytest.mark.parametrize(
    "kind, name, value, plain, text, literal",
    [
        ("langmuir", "capacity", [0, 100], [0, 100], "0, 100", "[0, 100]"),
        ("langmuir", "adsorption_rate", [2.5e-5] * 2, 2.5e-5, "2.5e-5", "2.5e-5"),
        ("langmuir", "capacity", None, None, "", "None"),
        ("inlet", "c", [1, 2], [1, 2], "1, 2", "[1, 2]"),
        ("inlet", "c", [[0, 1, 0, 0], [0] * 4], [[0, 1, 0, 0], [0] * 4],
         "[[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]]",
         "[[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]]"),
        ("column", "length", 0.1, 0.1, "0.1", "0.1"),
    ],
)
def test_parameter_values_as_plain_values_text_and_code(kind, name, value, plain, text, literal):
    obj = _owner(kind, **({} if value is None else {name: value}))
    assert plain_value(obj, name) == plain
    assert format_value(obj, name) == text
    assert code_literal(obj, name) == literal


@pytest.mark.parametrize(
    "name, text, error, stored",
    [
        ("capacity", "10, 20", None, [10, 20]),
        ("capacity", "5", None, [5, 5]),
        ("capacity", "abc", "Enter a number", None),
        ("capacity", "'x'", "Cannot cast", None),
    ],
)
def test_assign_literal_sets_valid_text_and_reports_invalid_text(name, text, error, stored):
    binding = _owner("langmuir")
    message = assign_literal(binding, name, text)
    if error is None:
        assert message is None
        assert list(binding.capacity) == stored
    else:
        assert error in message


def test_assign_literal_reports_cadet_process_bounds():
    column = _owner("column")
    assert "upper bound" in assign_literal(column, "total_porosity", "1.5")
    assert column.total_porosity is None


@pytest.mark.parametrize(
    "x, digits, text",
    [(1e-7, None, "1e-7"), (1e20, None, "1e20"), (0.5, None, "0.5"),
     (1 / 3, 3, "0.333"), (True, None, "True"), (None, None, "None")],
)
def test_number_text_is_compact(x, digits, text):
    assert number_text(x, digits) == text


def test_value_html_names_components_when_values_differ():
    binding = _owner("langmuir", capacity=[0, 100], adsorption_rate=[2.5e-5] * 2)
    assert value_html(binding, "capacity") == "Salt: 0, Protein: 100"
    assert value_html(binding, "adsorption_rate") == "2.5 × 10<sup>−5</sup>"
    assert value_html(_owner("column"), "length") is None


@pytest.mark.parametrize(
    "latex, html",
    [
        (r"\frac{\mathrm{m}^{2}_{\mathrm{IV}}}{\mathrm{s}}", "m<sup>2</sup><sub>IV</sub>/s"),
        (r"\frac{\mathrm{m}^{3}}{\mathrm{mol}\cdot\mathrm{s}}", "m<sup>3</sup>/(mol·s)"),
    ],
)
def test_unit_html_renders_cadet_process_units(latex, html):
    assert unit_html(latex) == html


def test_parameter_names_list_required_parameters_first():
    names = parameter_names(_owner("column"))
    required = sorted(LumpedRateModelWithoutPores(CS, "c").required_parameters)
    assert names[: len(required)] == required
    assert "c" in names[len(required):]


def test_parameter_paths_reach_units_and_binding_models(pulse_process):
    column = pulse_process.flow_sheet.column
    column.binding_model = Langmuir(pulse_process.component_system, "langmuir")
    prefixes = [prefix for prefix, _owner in parameter_owners(pulse_process)]
    assert prefixes == [
        "flow_sheet.inlet", "flow_sheet.column", "flow_sheet.column.binding_model",
        "flow_sheet.outlet",
    ]

    set_by_path(pulse_process, "flow_sheet.column.length", 0.2)
    assert column.length == 0.2
    assert resolve_path(pulse_process, "flow_sheet.column.length") == 0.2
    assert resolve_path(pulse_process, "flow_sheet.missing.length") is None
    assert has_parameter(pulse_process, "flow_sheet.column.binding_model.capacity")
    assert not has_parameter(pulse_process, "flow_sheet.missing.length")


def test_signal_ports_list_sinks_first_with_the_outlet_leading(pulse_process):
    flow_sheet = pulse_process.flow_sheet
    flow_sheet.add_unit(Outlet(pulse_process.component_system, "waste"))
    flow_sheet.add_connection(flow_sheet.column, flow_sheet.waste)
    flow_sheet.output_states[flow_sheet.column] = [0.5, 0.5]
    ports = list_signal_ports(pulse_process)
    assert [label for label, _value in ports] == [
        "outlet: Sink", "waste: Sink", "inlet: Source", "column: inlet", "column: outlet",
    ]
    assert dict(ports)["outlet: Sink"] == ("outlet", "inlet")

    result = SimpleNamespace(
        process=pulse_process,
        solution={"waste": {"inlet": 0, "outlet": 0}, "inlet": {"inlet": 0, "outlet": 0},
                  "outlet": {"inlet": 0, "outlet": 0}},
    )
    assert classify_signal_ports(result) == [
        ("outlet: Sink", ("outlet", "inlet")),
        ("waste: Sink", ("waste", "inlet")),
        ("inlet: Source", ("inlet", "outlet")),
    ]


def _times(*section_times):
    return SimpleNamespace(section_times=list(section_times), cycle_time=section_times[-1])


@pytest.mark.parametrize(
    "process, step",
    [
        (_times(0.0, 600.0), 0.12),
        (_times(0.0, 2.0, 600.0), 0.1),
        (_times(0.0, 0.01, 600.0), 0.03),
        (_times(0.0, 20000.0), 1.0),
    ],
)
def test_output_time_step_follows_cycle_and_shortest_section(process, step):
    assert output_time_step(process) == pytest.approx(step)


def test_simulator_output_grid_uses_the_output_time_step():
    time = Simulator().get_solution_time(_times(0.0, 600.0))
    assert len(time) == 5001
    assert np.diff(time).max() == pytest.approx(0.12)
