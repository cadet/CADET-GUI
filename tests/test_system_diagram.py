from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.cadetprocessadapter import (
    INSTRUMENT_TEMPLATES,
    active_inlets,
    friendly_signal_options,
    signal_label,
)
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget
from cadetgui.widgets.composite.system_diagram import SystemDiagram, render_system_svg

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def _states(html: str) -> dict[str, str]:
    return dict(re.findall(r'data-unit="(\w+)" data-state="(\w+)"', html))


def _bound(template: str = "Pulse Injection"):
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    cw._model_picker.value = INSTRUMENT_TEMPLATES[template]
    return iw, cw


def test_active_units_are_drawn_and_bypassed_units_are_left_out():
    iw = InstrumentWidget()
    iw._unit_checkboxes["tubing_pre_column"].value = True

    states = _states(iw._diagram.root.value)

    assert states["column"] == "active"
    assert states["tubing_pre_column"] == "active"
    assert states["outlet"] == "active"
    assert "tubing_post_column" not in states
    assert "tubing_detectors" not in states
    assert "sample_loop" not in states
    assert states["mixer"] == "bypassed"
    assert "Not in the flow path" in iw._diagram.root.value
    assert "Tubing (post column)" in iw._diagram.root.value


def test_diagram_updates_when_a_unit_is_toggled():
    iw = InstrumentWidget()
    assert "column" in _states(iw._diagram.root.value)

    iw._unit_checkboxes["column"].value = False
    assert "column" not in _states(iw._diagram.root.value)

    iw._unit_checkboxes["mixer"].value = True
    assert _states(iw._diagram.root.value)["mixer"] == "active"


def test_diagram_follows_the_sample_loop():
    iw = InstrumentWidget()
    assert "sample_loop" not in _states(iw._diagram.root.value)

    iw._sample_loop_checkbox.value = True

    assert _states(iw._diagram.root.value)["sample_loop"] == "active"


def test_only_inlets_the_template_uses_are_drawn():
    iw, cw = _bound("Step")
    states = _states(iw._diagram.root.value)
    assert states["buffer_b"] == "active"
    assert not {"buffer_a", "buffer_c", "buffer_d", "feed_inlet"} & states.keys()

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    states = _states(iw._diagram.root.value)
    assert states["buffer_a"] == "active"
    assert "buffer_b" not in states
    assert states["sample_loop"] == "active"

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Load–Wash–Elute (LWE)"]
    states = _states(iw._diagram.root.value)
    assert {"buffer_a", "buffer_b"} <= states.keys()
    assert not {"buffer_c", "buffer_d"} & states.keys()


def test_breakthrough_draws_the_feed_inlet():
    iw, _cw = _bound("Breakthrough")

    states = _states(iw._diagram.root.value)

    assert states["feed_inlet"] == "active"
    assert not {"buffer_a", "buffer_b", "buffer_c", "buffer_d"} & states.keys()


def test_active_inlets_are_read_from_the_process_events():
    _iw, cw = _bound("Load–Wash–Elute (LWE)")
    assert active_inlets(cw.process) == ["buffer_a", "buffer_b"]


def test_invalid_system_replaces_the_diagram_with_a_note():
    iw = InstrumentWidget()
    iw._sample_loop_checkbox.value = True
    iw._loop_volume_field.value = -1.0

    assert "<svg" not in iw._diagram.root.value
    assert "invalid" in iw._diagram.root.value


def test_unknown_inlets_draw_one_generic_inlet():
    html = render_system_svg({"mixer", "column", "outlet", "waste"}, inlets=None)

    assert _states(html)["inlet"] == "active"
    assert "buffer_a" not in _states(html)


def test_diagram_is_one_self_contained_svg():
    diagram = SystemDiagram()
    iw = InstrumentWidget()
    diagram.update(iw.flow_sheet, iw.bypass_units(), ["buffer_a"])

    html = diagram.root.value

    assert html.count("<svg xmlns") == 1
    assert "http" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "<image" not in html and "foreignObject" not in html and "data:" not in html
    assert "light-dark" not in html and "background" not in html


@pytest.mark.parametrize(
    ("unit", "port", "label"),
    [
        ("outlet", "inlet", "Process outlet"),
        ("waste", "inlet", "Waste outlet"),
        ("column", "outlet", "Column outlet"),
        ("tubing_detectors", "outlet", "Tubing (detectors) outlet"),
        ("buffer_a", "outlet", "Buffer A"),
    ],
)
def test_signal_labels_are_plain_names(unit, port, label):
    assert signal_label(unit, port) == label
    assert friendly_signal_options([("raw", (unit, port))]) == [(label, (unit, port))]


_ALL_UNITS = {
    "buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet", "mixer",
    "tubing_pre_injection", "sample_loop", "tubing_pre_column", "column",
    "tubing_post_column", "tubing_detectors", "outlet", "waste",
}  # fmt: skip
_ALL_INLETS = ["buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet"]
_SVG = "{http://www.w3.org/2000/svg}"


def _root(html: str) -> ET.Element:
    return ET.fromstring(html[html.index("<svg") : html.rindex("</svg>") + len("</svg>")])


def _symbols_by_unit(html: str) -> dict[str, list[str]]:
    return {
        g.get("data-unit"): [s.get("data-symbol") for s in g.iter(_SVG + "svg")]
        for g in _root(html).iter(_SVG + "g")
        if g.get("data-unit")
    }


def _box(node: ET.Element) -> tuple[float, float, float, float]:
    x, y = float(node.get("x")), float(node.get("y"))
    return x, y, x + float(node.get("width")), y + float(node.get("height"))


def test_symbols_ship_inside_the_package():
    import cadetgui

    pid = Path(cadetgui.__file__).parent / "assets" / "pid"
    names = {p.name for p in pid.glob("*.drawio.svg")}
    for symbol in (
        "Column", "Mixer", "SampleLoop", "Inlet", "InletA", "InletB", "InletC", "InletD",
        "Outlet", "UVSensor", "CondSensor",
    ):  # fmt: skip
        assert f"{symbol}.drawio.svg" in names

    package_data = (Path(cadetgui.__file__).parents[1] / "pyproject.toml").read_text()
    assert '"assets/pid/*.svg"' in package_data


def test_full_diagram_is_valid_xml_built_from_the_pid_symbols():
    html = render_system_svg(_ALL_UNITS, (), _ALL_INLETS)

    symbols = _symbols_by_unit(html)

    assert symbols["buffer_a"] == ["InletA"]
    assert symbols["buffer_b"] == ["InletB"]
    assert symbols["buffer_c"] == ["InletC"]
    assert symbols["buffer_d"] == ["InletD"]
    assert symbols["feed_inlet"] == ["Inlet"]
    assert symbols["mixer"] == ["Mixer"]
    assert symbols["sample_loop"] == ["SampleLoop"]
    assert symbols["column"] == ["Column"]
    assert symbols["tubing_detectors"] == ["UVSensor", "CondSensor"]
    assert symbols["outlet"] == ["Outlet"]
    assert symbols["waste"] == ["Outlet"]
    assert symbols["tubing_pre_column"] == []


def test_symbol_content_is_the_drawn_pid_geometry():
    html = render_system_svg({"mixer", "column", "outlet"}, (), ["buffer_a"])
    root = _root(html)
    column = next(s for s in root.iter(_SVG + "svg") if s.get("data-symbol") == "Column")

    assert column.get("viewBox") == "0 0 321 82"
    assert "Column" in "".join(column.itertext())
    assert column.find(f".//{_SVG}rect") is not None


def test_symbols_stay_inside_the_canvas_and_never_overlap():
    for units, bypassed, inlets in (
        (_ALL_UNITS, (), _ALL_INLETS),
        (_ALL_UNITS - {"sample_loop"}, ("mixer",), ["buffer_b", "feed_inlet"]),
        ({"mixer", "column", "outlet", "waste"}, (), None),
    ):
        root = _root(render_system_svg(units, bypassed, inlets))
        _, _, w, h = (float(v) for v in root.get("viewBox").split())
        boxes = [_box(s) for s in root.iter(_SVG + "svg") if s.get("data-symbol")]

        for x0, y0, x1, y1 in boxes:
            assert 0 <= x0 and x1 <= w and 0 <= y0 and y1 <= h
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_bypassed_mixer_is_dimmed_and_marked():
    html = render_system_svg({"mixer", "column", "outlet"}, ("mixer",), ["buffer_a"])
    mixer = next(
        g for g in _root(html).iter(_SVG + "g") if g.get("data-unit") == "mixer"
    )

    assert mixer.get("data-state") == "bypassed"
    assert mixer.find(f"{_SVG}g[@opacity]") is not None
    assert mixer.find(f".//{_SVG}rect[@stroke-dasharray]") is not None
    assert "bypassed" in "".join(mixer.itertext())


def test_generic_inlet_uses_the_plain_inlet_symbol():
    html = render_system_svg({"mixer", "column", "outlet"}, inlets=None)

    assert _symbols_by_unit(html)["inlet"] == ["Inlet"]


def test_symbol_files_reduce_to_plain_theme_aware_svg():
    from cadetgui.widgets.composite.system_diagram import _load_symbol

    for name in ("Column", "Mixer", "SampleLoop", "Inlet", "UVSensor", "CondSensor"):
        sym = _load_symbol(name)
        ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{sym.body}</svg>')
        assert "light-dark" not in sym.body and "base64" not in sym.body
        assert "data-cell-id" not in sym.body
        assert _load_symbol(name) is sym
