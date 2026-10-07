from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.cadetprocessadapter import (
    BYPASSABLE_UNITS,
    INSTRUMENT_TEMPLATES,
    active_inlets,
    friendly_signal_options,
    inlet_contents,
    signal_label,
)
from cadetgui.configuration_store import ConfigurationState, InstrumentState
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget
from cadetgui.widgets.composite.system_diagram import (
    HARDWARE_ONLY_NOTE,
    SystemDiagram,
    recipe_diagram_svg,
    render_system_svg,
)

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


def _captions(html: str) -> list[str]:
    return re.findall(r'<div style="font-size:12px[^>]*>([^<]*)</div>', html)


def test_fresh_system_pane_shows_breakthrough_feed_path_with_buffers_unused():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    assert type(cw.process).__name__ == "Breakthrough"

    states = _states(iw._diagram.root.value)

    assert states["feed_inlet"] == "active"
    assert {states[b] for b in ("buffer_a", "buffer_b", "buffer_c", "buffer_d")} == {"unused"}


def test_step_equilibrates_with_buffer_a_then_switches_to_buffer_b():
    iw, _cw = _bound("Step")
    states = _states(iw._diagram.root.value)

    assert {states["buffer_a"], states["buffer_b"]} == {"active"}
    assert {states[u] for u in ("buffer_c", "buffer_d", "feed_inlet")} == {"unused"}


def test_switching_template_moves_the_active_state_between_feed_and_buffers():
    iw, cw = _bound("Pulse Injection")
    states = _states(iw._diagram.root.value)
    assert states["buffer_a"] == "active"
    assert {states[u] for u in ("buffer_b", "buffer_c", "buffer_d", "feed_inlet")} == {"unused"}
    assert states["sample_loop"] == "active"

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Load–Wash–Elute (LWE)"]
    states = _states(iw._diagram.root.value)
    assert {states["buffer_a"], states["buffer_b"]} == {"active"}
    assert {states["buffer_c"], states["buffer_d"], states["feed_inlet"]} == {"unused"}

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Breakthrough"]
    states = _states(iw._diagram.root.value)
    assert states["feed_inlet"] == "active"
    assert "active" not in {states[b] for b in ("buffer_a", "buffer_b", "buffer_c", "buffer_d")}


def test_unused_inlets_are_dimmed_and_labelled_not_hidden():
    iw, _cw = _bound("Breakthrough")
    root = _root(iw._diagram.root.value)
    groups = {g.get("data-unit"): g for g in root.iter(_SVG + "g") if g.get("data-unit")}

    unused = groups["buffer_c"]
    assert unused.find(f"{_SVG}g[@opacity]") is not None
    assert "unused" in "".join(unused.itertext())
    assert groups["buffer_c"].find(f".//{_SVG}svg") is not None
    feed = "".join(groups["feed_inlet"].itertext())
    assert "Feed inlet" in feed and "sample components" in feed
    assert groups["feed_inlet"].find(f"{_SVG}g[@opacity]") is None
    assert "Buffers via mixer" in "".join(root.itertext())


def test_breakthrough_caption_names_the_sample_components_on_the_feed_path():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    cw.components = ["Salt", "Protein"]

    captions = _captions(iw._diagram.root.value)

    assert captions[0] == (
        "Feed inlet carries the sample components (Salt, Protein) straight into the column."
    )
    assert captions[1] == "Not used: buffers A\u2013D."


def test_step_caption_names_the_buffer_path():
    iw, cw = _bound("Step")
    cw.components = ["Salt", "Protein"]
    captions = _captions(iw._diagram.root.value)

    assert captions[0] == (
        "The system starts pre-equilibrated with buffer A; at t=0 the flow switches to buffer B."
    )
    assert captions[1] == "Buffer B carries Salt, Protein into the column."
    assert captions[2] == "Not used: the feed inlet and buffers C and D."


def test_loop_templates_caption_says_the_sample_sits_in_the_loop():
    iw, cw = _bound("Load–Wash–Elute (LWE)")
    cw.components = ["Salt", "Protein"]
    captions = _captions(iw._diagram.root.value)

    assert captions[0].startswith("Buffers A and B carry ")
    assert "pre-filled in the sample loop" in captions[1]
    assert captions[2] == "Not used: the feed inlet and buffers C and D."

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    captions = _captions(iw._diagram.root.value)
    assert captions[0].startswith("Buffer A carries plain buffer")


def test_caption_mentions_the_mixer_only_while_it_is_in_the_path():
    iw, _cw = _bound("Step")
    assert "through the mixer" not in _captions(iw._diagram.root.value)[0]

    iw._unit_checkboxes["mixer"].value = True

    assert "through the mixer" in _captions(iw._diagram.root.value)[0]


def test_inlet_contents_lists_only_driven_inlets_and_a_filled_loop():
    _iw, cw = _bound("Step")
    cw.components = ["Salt", "Protein"]
    assert inlet_contents(cw.process) == {"buffer_a": [], "buffer_b": ["Salt", "Protein"]}

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    assert inlet_contents(cw.process) == {"buffer_a": [], "sample_loop": ["Salt", "Protein"]}

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Breakthrough"]
    assert inlet_contents(cw.process) == {"feed_inlet": ["Salt", "Protein"]}


def test_long_component_lists_are_summarised_in_the_label():
    names = [f"Component number {i}" for i in range(5)]
    html = render_system_svg(_ALL_UNITS, (), ["feed_inlet"], {"feed_inlet": names})

    assert "(5 components)" in html


def test_component_names_wrap_onto_short_lines_and_stay_on_the_canvas():
    names = ["Component 1", "Component 2"]
    carries = {"buffer_a": names, "buffer_b": names}
    html = render_system_svg(_ALL_UNITS, (), ["buffer_a", "buffer_b"], carries)
    root = _root(html)

    text = [t for t in root.iter(_SVG + "text") if "Component" in "".join(t.itertext())]
    assert text
    for t in text:
        assert all(len(span.text or "") <= 20 for span in t.iter(_SVG + "tspan"))
        xs = [float(span.get("x")) for span in t.iter(_SVG + "tspan")]
        half = max(len(span.text or "") for span in t.iter(_SVG + "tspan")) * 7.4 / 2
        assert min(xs) - half >= 0


def test_unknown_inlets_add_no_usage_caption():
    html = render_system_svg({"mixer", "column", "outlet", "waste"}, inlets=None)

    assert _captions(html) == []


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
    assert _symbols_by_unit(html)["inlet"] == ["Inlet"]
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
        ("outlet", "inlet", "Outlet"),
        ("waste", "inlet", "Waste outlet"),
        ("column", "outlet", "Column outlet"),
        ("tubing_detectors", "outlet", "Tubing (detectors) outlet"),
        ("buffer_a", "outlet", "Buffer A inlet"),
        ("feed_inlet", "outlet", "Feed inlet"),
        ("column", "inlet", "Column inlet"),
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
        (_ALL_UNITS, (), ["feed_inlet"]),
        (_ALL_UNITS - {"sample_loop"}, (), []),
        (_ALL_UNITS - {"sample_loop"}, (), ["feed_inlet"]),
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


def test_symbol_files_reduce_to_plain_theme_aware_svg():
    from cadetgui.widgets.composite._pid_symbols import load_symbol

    for name in ("Column", "Mixer", "SampleLoop", "Inlet", "UVSensor", "CondSensor"):
        sym = load_symbol(name)
        ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{sym.body}</svg>')
        assert "light-dark" not in sym.body and "base64" not in sym.body
        assert "data-cell-id" not in sym.body
        assert load_symbol(name) is sym


def test_template_dropdown_lists_the_registry_and_shows_the_current_template():
    iw = InstrumentWidget()
    assert iw._template_picker.layout.display == "none"

    cw = ConfigurationWidget(instrument=iw)

    assert iw._template_picker.layout.display == ""
    assert iw._template_picker.option_labels == list(INSTRUMENT_TEMPLATES)
    assert iw._template_picker.value == "Breakthrough"
    assert cw._model_picker.value is INSTRUMENT_TEMPLATES["Breakthrough"]


def test_picking_a_template_in_the_system_pane_drives_the_configuration_and_diagram():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)

    iw._template_picker.value = "Pulse Injection"

    assert cw._model_picker.value is INSTRUMENT_TEMPLATES["Pulse Injection"]
    assert type(cw.process).__name__ == "PulseInjection"
    states = _states(iw._diagram.root.value)
    assert states["buffer_a"] == "active"
    assert {states[u] for u in ("buffer_b", "buffer_c", "buffer_d", "feed_inlet")} == {"unused"}
    assert "sample_loop" in states


def test_picking_a_loop_template_in_the_system_pane_locks_the_loop_on():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    assert not iw._sample_loop_checkbox.value

    iw._template_picker.value = "Pulse Injection"
    assert iw._sample_loop_checkbox.value
    assert iw._sample_loop_checkbox.disabled

    iw._template_picker.value = "Breakthrough"
    assert not iw._sample_loop_checkbox.value
    assert not iw._sample_loop_checkbox.disabled
    assert cw._model_picker.value is INSTRUMENT_TEMPLATES["Breakthrough"]


def test_configuration_picker_updates_the_system_dropdown_without_a_loop():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    built = []
    original = cw._on_process_built
    cw._on_process_built = lambda process: (built.append(process), original(process))[1]
    calls = []
    iw._on_template_select = calls.append

    cw._model_picker.value = INSTRUMENT_TEMPLATES["Step"]

    assert iw._template_picker.value == "Step"
    assert calls == []
    assert len(built) == 1


def test_system_dropdown_pick_builds_the_process_once():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    built = []
    original = cw._on_process_built
    cw._on_process_built = lambda process: (built.append(process), original(process))[1]

    iw._template_picker.value = "Step"

    assert len(built) == 1
    assert iw._template_picker.value == "Step"


def test_characterization_workbench_shows_hardware_only_without_a_template_picker():
    from cadetgui.widgets.composite import CharacterizationWorkbenchWidget

    wb = CharacterizationWorkbenchWidget()
    html = wb.instrument._diagram.root.value

    assert wb.instrument.hardware_only and not wb.configuration.show_process_template
    assert wb.instrument._template_picker.layout.display == "none"
    assert "unused" not in html and HARDWARE_ONLY_NOTE in html
    assert not wb.instrument._sample_loop_checkbox.disabled


def _column_caption(html: str) -> list[str]:
    group = next(
        g for g in _root(html).iter(_SVG + "g") if g.get("data-unit") == "column"
    )
    return [t.text for t in group.iter(_SVG + "tspan") if t.text and "(" in t.text]


def test_column_model_is_captioned_under_the_column_and_follows_the_picker():
    from cadetgui.cadetprocessadapter import COLUMN_MODELS

    iw, cw = _bound("Breakthrough")
    name = "Lumped Rate Model With Pores (LRMP)"
    assert _column_caption(iw._diagram.root.value) == ["Lumped Rate Model Without Pores (LRM)"]

    cw._column_picker.value = COLUMN_MODELS[name]

    assert _column_caption(iw._diagram.root.value) == [name]
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Step"]
    assert _column_caption(iw._diagram.root.value) == [name]


def test_column_caption_is_absent_without_a_configuration_or_a_column():
    iw = InstrumentWidget()
    assert "Lumped Rate Model" not in iw._diagram.root.value

    ConfigurationWidget(instrument=iw)
    assert "Lumped Rate Model" in iw._diagram.root.value

    iw._unit_checkboxes["column"].value = False
    assert "Lumped Rate Model" not in iw._diagram.root.value


def test_column_caption_stays_inside_the_canvas_and_clear_of_other_symbols():
    for units, inlets in (
        (_ALL_UNITS, _ALL_INLETS),
        (_ALL_UNITS - {"sample_loop"}, ["feed_inlet"]),
    ):
        root = _root(
            render_system_svg(units, (), inlets, column_model="Lumped Rate Model With Pores (LRMP)")
        )
        _, _, w, h = (float(v) for v in root.get("viewBox").split())
        boxes = [_box(s) for s in root.iter(_SVG + "svg") if s.get("data-symbol")]
        column = next(s for s in root.iter(_SVG + "svg") if s.get("data-symbol") == "Column")
        cx0, _, cx1, cy1 = _box(column)
        text = next(
            t for t in root.iter(_SVG + "text") if "LRMP" in "".join(t.itertext())
        )
        ty = float(text.find(_SVG + "tspan").get("y"))

        assert ty > cy1 and ty + 4 <= h
        assert cx0 <= float(text.find(_SVG + "tspan").get("x")) <= cx1
        for x0, y0, x1, y1 in boxes:
            if (x0, x1) != (cx0, cx1):
                assert x1 <= cx0 or x0 >= cx1 or y0 >= ty + 4 or y1 <= ty - 14


def test_highlighted_units_carry_the_data_attribute_and_accent_halo():
    html = render_system_svg(_ALL_UNITS, (), _ALL_INLETS, highlight=["column"])
    root = _root(html)
    column = next(g for g in root.iter(_SVG + "g") if g.get("data-unit") == "column")

    assert column.get("data-highlight") == "true"
    assert column.find(f".//{_SVG}rect[@rx='8']") is not None
    other = next(g for g in root.iter(_SVG + "g") if g.get("data-unit") == "mixer")
    assert other.get("data-highlight") is None
    assert "Characterized here: Column" in html


def test_observe_marker_is_drawn_at_the_units_outlet():
    html = render_system_svg(_ALL_UNITS, (), _ALL_INLETS, observe="column")
    root = _root(html)
    markers = [g for g in root.iter(_SVG + "g") if g.get("data-observe")]

    assert len(markers) == 1
    assert markers[0].get("data-observe") == "column"
    assert "measured here" in "".join(markers[0].itertext())


def test_observe_on_a_unit_not_drawn_is_named_in_the_caption_not_silently_dropped():
    units = _ALL_UNITS - {"column"}
    html = render_system_svg(units, (), _ALL_INLETS, observe="column")

    assert not any(g.get("data-observe") for g in _root(html).iter(_SVG + "g"))
    assert "Measured here: Column" in html


def test_compact_diagram_is_narrower_than_the_full_diagram_and_keeps_bypass_captions():
    full = render_system_svg(_ALL_UNITS, ("tubing_pre_column",), _ALL_INLETS)
    compact = render_system_svg(_ALL_UNITS, ("tubing_pre_column",), _ALL_INLETS, compact=True)

    full_w = float(_root(full).get("viewBox").split()[2])
    compact_w = float(_root(compact).get("viewBox").split()[2])

    assert compact_w < full_w
    assert "Not in the flow path" in compact
    assert "Buffers via mixer" not in compact


def test_compact_diagram_keeps_highlight_and_observe_captions():
    html = render_system_svg(
        _ALL_UNITS, (), _ALL_INLETS, highlight=["mixer"], observe="mixer", compact=True
    )

    assert "Characterized here: Mixer" in html
    assert "measured here" in html
    mixer = next(g for g in _root(html).iter(_SVG + "g") if g.get("data-unit") == "mixer")
    assert mixer.get("data-highlight") == "true"


def test_default_call_is_unaffected_by_the_new_keyword_only_arguments():
    baseline = render_system_svg(_ALL_UNITS, (), _ALL_INLETS)
    same = render_system_svg(_ALL_UNITS, (), _ALL_INLETS, None, (), None)

    assert baseline == same
    assert "data-highlight" not in baseline
    assert "data-observe" not in baseline
    assert "measured here" not in baseline


def _recipe_state(*, bypass=(), include_sample_loop=False, instrument=True):
    return ConfigurationState(
        components=["A"],
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="Linear",
        template_key="Breakthrough",
        instrument=(
            InstrumentState(bypass_units=list(bypass), include_sample_loop=include_sample_loop)
            if instrument
            else None
        ),
    )


def test_recipe_diagram_svg_omits_a_bypassed_column():
    html = recipe_diagram_svg(_recipe_state(bypass=["column"]))
    states = _states(html)

    assert "column" not in states
    assert states["mixer"] == "active"


def test_recipe_diagram_svg_shows_the_sample_loop_when_enabled():
    without_loop = _states(recipe_diagram_svg(_recipe_state()))
    with_loop = _states(recipe_diagram_svg(_recipe_state(include_sample_loop=True)))

    assert "sample_loop" not in without_loop
    assert with_loop["sample_loop"] == "active"


def test_recipe_diagram_svg_without_an_instrument_is_a_minimal_column_diagram():
    html = recipe_diagram_svg(_recipe_state(instrument=False))
    states = _states(html)

    assert states == {"column": "active"}


def test_recipe_diagram_svg_is_compact_by_default_and_valid_xml():
    default_html = recipe_diagram_svg(_recipe_state())
    full_html = recipe_diagram_svg(_recipe_state(), compact=False)

    default_w = float(_root(default_html).get("viewBox").split()[2])
    full_w = float(_root(full_html).get("viewBox").split()[2])

    assert default_w <= full_w


def test_set_highlight_redraws_the_bound_diagram():
    diagram = SystemDiagram()
    iw = InstrumentWidget()
    diagram.update(iw.flow_sheet, iw.bypass_units(), ["buffer_a"])

    diagram.set_highlight(["column"], observe="column")

    html = diagram.root.value
    assert "Characterized here: Column" in html
    column = next(g for g in _root(html).iter(_SVG + "g") if g.get("data-unit") == "column")
    assert column.get("data-highlight") == "true"

    diagram.set_highlight([])
    assert "data-highlight" not in diagram.root.value


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize(
    "observe, bypassed",
    [
        ("column", ["tubing_pre_injection", "tubing_post_column", "tubing_detectors"]),
        ("tubing_detectors", ["tubing_pre_injection", "tubing_post_column"]),
        ("tubing_pre_column", ["column", "tubing_pre_injection", "tubing_post_column",
                               "tubing_detectors"]),
    ],
)
def test_measured_here_label_sits_above_every_other_label(observe, bypassed, compact):
    units = {
        "buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet", "mixer",
        "sample_loop", "outlet", "waste", *BYPASSABLE_UNITS,
    } - set(bypassed)
    out = render_system_svg(
        units, bypassed, observe=observe, highlight={"column"},
        column_model="Lumped Rate Model With Pores", compact=compact,
    )
    root = ET.fromstring(out[out.index("<svg"):out.rindex("</svg>") + 6])
    label_y, tops = None, []

    def walk(el, in_marker=False):
        nonlocal label_y
        tag = el.tag.split("}")[-1]
        in_marker = in_marker or el.get("data-observe") is not None
        if tag == "svg" and el is not root:
            tops.append(float(el.get("y", 0)))
            return
        if tag == "tspan":
            if in_marker:
                label_y = float(el.get("y"))
            else:
                tops.append(float(el.get("y")) - 14)
        for child in el:
            walk(child, in_marker)

    walk(root)
    assert label_y is not None
    assert label_y < min(tops)


def test_hardware_only_diagram_draws_every_inlet_plainly_with_the_method_note():
    iw = InstrumentWidget(hardware_only=True)
    cw = ConfigurationWidget(instrument=iw, show_process_template=False)
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    html = iw._diagram.root.value

    states = _states(html)
    assert {states[u] for u in ("buffer_a", "buffer_b", "buffer_c", "buffer_d", "feed_inlet")} == {
        "active"
    }
    assert "unused" not in html and "carries" not in html
    assert HARDWARE_ONLY_NOTE in html
    assert iw._template_picker.layout.display == "none"


def test_default_diagram_still_marks_unused_inlets_from_the_template():
    iw, _cw = _bound("Pulse Injection")
    html = iw._diagram.root.value

    assert "(unused)" in html and HARDWARE_ONLY_NOTE not in html
    assert iw._template_picker.layout.display == ""


def test_hardware_only_is_ignored_for_compact_diagrams():
    units = {"buffer_a", "feed_inlet", "mixer", "column", "outlet"}
    assert render_system_svg(units, compact=True, hardware_only=True) == render_system_svg(
        units, compact=True
    )
