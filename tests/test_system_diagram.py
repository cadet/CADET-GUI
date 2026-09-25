from __future__ import annotations

import re
import warnings

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

    assert html.count("<svg") == 1 and html.count("</svg>") == 1
    assert "http" not in html.replace("http://www.w3.org/2000/svg", "")


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
