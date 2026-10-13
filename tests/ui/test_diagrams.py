"""SVG diagrams: valid self-contained SVG, active/bypassed/unused units, highlight, observe."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import cadetgui
import pytest
from cadetgui.instrument.process_builder import build_process
from cadetgui.instrument.system import active_inlets, inlet_contents
from cadetgui.io.configuration_store import ConfigurationState, InstrumentState
from cadetgui.widgets.diagrams import (
    SystemDiagram,
    recipe_diagram_svg,
    render_flow_sheet_svg,
    render_system_svg,
)
from cadetgui.widgets.diagrams.instrument import HARDWARE_ONLY_NOTE
from cadetgui.widgets.diagrams.svg import load_symbol
from CADETProcess.processModel import (
    ComponentSystem,
    Cstr,
    FlowSheet,
    Inlet,
    LumpedRateModelWithoutPores,
    Outlet,
)

SVG = "{http://www.w3.org/2000/svg}"
BUFFERS = ["buffer_a", "buffer_b", "buffer_c", "buffer_d"]
INLETS = [*BUFFERS, "feed_inlet"]
ALL_UNITS = {
    *INLETS, "mixer", "tubing_pre_injection", "sample_loop", "tubing_pre_column", "column",
    "tubing_post_column", "tubing_detectors", "outlet", "waste",
}  # fmt: skip
NO_LOOP = ALL_UNITS - {"sample_loop"}

# id -> (render_system_svg args, kwargs, expected data-state per unit; None = not drawn)
SYSTEMS = {
    "all inlets": (
        (ALL_UNITS, (), INLETS),
        {},
        {"buffer_a": "active", "feed_inlet": "active", "mixer": "active", "column": "active"},
    ),
    "feed only, mixer bypassed": (
        (NO_LOOP, ("mixer",), ["feed_inlet"]),
        {},
        {"feed_inlet": "active", "buffer_a": "unused", "mixer": "bypassed", "sample_loop": None},
    ),
    "two buffers and loop": (
        (ALL_UNITS, (), ["buffer_a", "buffer_b"], {"sample_loop": ["Protein"]}),
        {},
        {"buffer_b": "active", "buffer_c": "unused", "sample_loop": "active"},
    ),
    "inlets unknown": (
        ({"mixer", "column", "outlet", "waste"},),
        {},
        {"inlet": "active", "buffer_a": None, "column": "active"},
    ),
    "hardware only": (
        (ALL_UNITS, (), ["feed_inlet"]),
        {"hardware_only": True},
        {"buffer_c": "active", "feed_inlet": "active"},
    ),
    "compact column only": (({"column"},), {"compact": True}, {"column": "active", "mixer": None}),
}


def _svg_root(html: str) -> ET.Element:
    return ET.fromstring(html[html.index("<svg") : html.rindex("</svg>") + len("</svg>")])


def _states(html: str) -> dict[str, str]:
    return dict(re.findall(r'data-unit="(\w+)" data-state="(\w+)"', html))


def _groups(html: str) -> dict[str, ET.Element]:
    return {g.get("data-unit"): g for g in _svg_root(html).iter(SVG + "g") if g.get("data-unit")}


def _assert_self_contained_svg(html: str) -> None:
    root = _svg_root(html)
    assert root.tag == SVG + "svg" and html.count("<svg xmlns") == 1
    assert "http" not in html.replace("http://www.w3.org/2000/svg", "")
    assert not any(s in html for s in ("<image", "foreignObject", "data:", "light-dark"))


def _flow_sheet(*units, connections):
    flow_sheet = FlowSheet(units[0].component_system, "flow_sheet")
    for unit in units:
        flow_sheet.add_unit(unit)
    for origin, destination in connections:
        flow_sheet.add_connection(origin, destination)
    return flow_sheet


def _recycle_flow_sheet():
    cs = ComponentSystem(1)
    inlet, cstr, outlet = Inlet(cs, "inlet"), Cstr(cs, "cstr"), Outlet(cs, "outlet")
    column = LumpedRateModelWithoutPores(cs, "column")
    edges = [(inlet, cstr), (cstr, column), (column, outlet), (column, cstr)]
    return _flow_sheet(inlet, cstr, column, outlet, connections=edges)


def _recipe(*, bypass=(), loop=False, instrument=True):
    return ConfigurationState(
        components=["A"],
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="Linear",
        template_key="Breakthrough",
        instrument=InstrumentState(bypass_units=list(bypass), include_sample_loop=loop)
        if instrument
        else None,
    )


@pytest.mark.parametrize("args, kwargs, expected", SYSTEMS.values(), ids=SYSTEMS)
def test_system_diagram_is_self_contained_svg_with_unit_states(args, kwargs, expected):
    html = render_system_svg(*args, **kwargs)

    _assert_self_contained_svg(html)
    states = _states(html)
    for unit, state in expected.items():
        assert states.get(unit) == state, unit
    groups = _groups(html)
    for unit, state in states.items():
        dimmed = groups[unit].find(f"{SVG}g[@opacity]") is not None
        assert dimmed == (state in ("bypassed", "unused")), unit
    assert (HARDWARE_ONLY_NOTE in html) == kwargs.get("hardware_only", False)


@pytest.mark.parametrize("compact", [False, True])
def test_highlight_and_observe_mark_units_and_name_undrawn_ones(compact):
    html = render_system_svg(
        ALL_UNITS, (), INLETS, highlight=["column"], observe="column", compact=compact
    )
    groups = _groups(html)
    assert groups["column"].get("data-highlight") == "true"
    assert groups["mixer"].get("data-highlight") is None
    markers = [g.get("data-observe") for g in _svg_root(html).iter(SVG + "g")]
    assert [m for m in markers if m] == ["column"]

    undrawn = render_system_svg(ALL_UNITS - {"column"}, (), INLETS, observe="column")
    assert not any(g.get("data-observe") for g in _svg_root(undrawn).iter(SVG + "g"))
    assert "Column" in undrawn

    plain = render_system_svg(ALL_UNITS, (), INLETS)
    assert "data-highlight" not in plain and "data-observe" not in plain


@pytest.mark.parametrize(
    "recipe, expected",
    [
        (_recipe(), {"mixer": "active", "column": "active", "sample_loop": None}),
        (_recipe(bypass=["column"], loop=True), {"column": None, "sample_loop": "active"}),
        (_recipe(instrument=False), {"column": "active", "mixer": None}),
    ],
    ids=["default", "loop, column bypassed", "standalone column"],
)
def test_recipe_diagram_draws_the_saved_flow_path(recipe, expected):
    html = recipe_diagram_svg(recipe)

    _assert_self_contained_svg(html)
    states = _states(html)
    for unit, state in expected.items():
        assert states.get(unit) == state, unit


@pytest.mark.parametrize(
    "template, loop, active, carries",
    [
        ("Breakthrough", False, ["feed_inlet"], {"feed_inlet": ["Salt", "Protein"]}),
        ("Step", False, ["buffer_a", "buffer_b"], {"buffer_b": ["Salt", "Protein"]}),
        ("Pulse Injection", True, ["buffer_a"], {"sample_loop": ["Salt", "Protein"]}),
    ],
)
def test_template_processes_drive_the_inlet_states(template, loop, active, carries):
    state = ConfigurationState(
        components=["Salt", "Protein"],
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="Linear",
        template_key=template,
        instrument=InstrumentState(include_sample_loop=loop),
    )
    process = build_process(state)
    assert active_inlets(process) == active
    contents = inlet_contents(process)
    assert {k: v for k, v in contents.items() if v} == carries

    states = _states(render_system_svg(process.flow_sheet.units_dict, (), active, contents))
    assert {u for u in INLETS if states[u] == "active"} == set(active)


def test_system_diagram_widget_follows_updates_and_highlight():
    diagram = SystemDiagram()
    assert "<svg" not in diagram.root.value

    diagram.update(SimpleNamespace(units_dict=dict.fromkeys(ALL_UNITS)), ("mixer",), ["buffer_a"])
    assert _states(diagram.root.value)["mixer"] == "bypassed"

    diagram.set_highlight(["column"], observe="column")
    assert _groups(diagram.root.value)["column"].get("data-highlight") == "true"
    diagram.set_highlight([])
    assert "data-highlight" not in diagram.root.value

    diagram.update(None)
    assert "<svg" not in diagram.root.value


@pytest.mark.parametrize(
    "make_flow_sheet, n_units, n_edges",
    [
        (lambda p: p.flow_sheet, 3, 2),
        (lambda p: _recycle_flow_sheet(), 4, 4),
    ],
    ids=["pulse", "recycle loop"],
)
def test_flow_sheet_diagram_draws_every_unit_and_connection(
    pulse_process, make_flow_sheet, n_units, n_edges
):
    flow_sheet = make_flow_sheet(pulse_process)
    html = render_flow_sheet_svg(flow_sheet)

    _assert_self_contained_svg(html)
    for unit in flow_sheet.units:
        assert f">{unit.name}<" in html
    assert html.count('marker-end="url(#cg-arrow)"') == n_edges


def test_flow_sheet_diagram_of_an_empty_flow_sheet_is_a_note():
    html = render_flow_sheet_svg(FlowSheet(ComponentSystem(1), "flow_sheet"))
    assert "<svg" not in html and "no units" in html


@pytest.mark.parametrize(
    "name", ["Column", "Mixer", "SampleLoop", "Inlet", "InletA", "Outlet", "UVSensor", "CondSensor"]
)
def test_pid_symbols_ship_with_the_package_as_plain_svg(name):
    pid = Path(cadetgui.__file__).parent / "assets" / "pid"
    assert (pid / f"{name}.drawio.svg").is_file()

    symbol = load_symbol(name)
    ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{symbol.body}</svg>')
    assert not any(s in symbol.body for s in ("light-dark", "base64", "data-cell-id"))
    assert load_symbol(name) is symbol
