"""Element front-ends run against a fake anywidget model in headless Chromium."""
from __future__ import annotations

import pytest
from cadetgui.widgets.elements import (
    BoolField,
    ChoiceField,
    ChromatogramChart,
    ComponentListField,
    EventTimelineChart,
    FloatField,
    FloatListField,
    LineChart,
    SelectableTable,
    TextField,
)

MOUNT_JS = """async ({ esm, state }) => {
  const url = URL.createObjectURL(new Blob([esm], { type: "text/javascript" }));
  const mod = await import(url);
  const listeners = {};
  const saved = [];
  const model = {
    get: (key) => state[key],
    set: (key, value) => { state[key] = value; },
    save_changes: () => saved.push({ ...state }),
    on: (event, cb) => { (listeners[event] = listeners[event] || []).push(cb); },
  };
  const el = document.createElement("div");
  document.body.replaceChildren(el);
  mod.default.render({ model, el });
  window.view = {
    el,
    saved,
    q: (sel) => el.querySelector(sel),
    qa: (sel) => Array.from(el.querySelectorAll(sel)),
    change: (name, value) => {
      state[name] = value;
      (listeners["change:" + name] || []).forEach((cb) => cb());
    },
  };
}"""

UNIT = r"\frac{\mathrm{m}^{3}}{\mathrm{s}}"


class View:
    def __init__(self, page, widget):
        self.page = page
        state = {k: v for k, v in widget.get_state().items() if not k.startswith("_")}
        page.evaluate(MOUNT_JS, {"esm": widget._esm, "state": state})

    def js(self, body: str):
        return self.page.evaluate(f"() => {{ const v = window.view; {body} }}")

    def text(self, selector: str) -> str:
        return self.js(f"return v.q({selector!r}).textContent;")

    def saved(self) -> list:
        return self.js("return v.saved;")


@pytest.fixture(scope="module")
def mount(chromium):
    page = chromium.new_page()
    page.set_content("<html><body></body></html>")
    yield lambda widget: View(page, widget)
    page.close()


@pytest.mark.parametrize(
    "widget",
    [
        FloatField(),
        TextField(),
        BoolField(),
        ChoiceField(options=[("A", 1)]),
        ComponentListField(),
        FloatListField(),
        SelectableTable(options=[("a", 1)]),
        LineChart(),
        EventTimelineChart(),
        ChromatogramChart(),
    ],
    ids=lambda w: type(w).__name__,
)
def test_every_view_renders_its_default_state(mount, widget):
    view = mount(widget)

    assert view.js("return v.el.children.length;") == 1


@pytest.mark.parametrize(
    "widget",
    [
        FloatField(label="Flow"),
        TextField(label="Flow"),
        BoolField(label="Flow"),
        ChoiceField(label="Flow", options=[("A", 1)]),
    ],
    ids=lambda w: type(w).__name__,
)
def test_field_views_show_label_error_and_disabled_state(mount, widget):
    view = mount(widget)
    assert view.text(".cadetgui-field-label") == "Flow"
    assert view.js("return v.q('.cadetgui-field-error').hidden;") is True

    view.js("v.change('error', 'too big');")
    assert view.text(".cadetgui-field-error") == "too big"
    assert view.js("return v.q('.cadetgui-field-error').hidden;") is False

    view.js("v.change('label', 'Rate');")
    assert view.text(".cadetgui-field-label") == "Rate"

    view.js("v.change('disabled', true);")
    assert view.js("return v.qa('input, select').every((n) => n.disabled);") is True
    assert view.js("return v.q('.cadetgui-field').classList.contains('cadetgui-field-disabled');")

    view.js("v.change('disabled', false);")
    assert view.js("return v.qa('input, select').some((n) => n.disabled);") is False


def test_float_field_commits_parsed_numbers_and_ignores_garbage(mount):
    view = mount(FloatField(value=1.0))

    view.js("v.q('input').value = '2.5e-3'; v.q('input').dispatchEvent(new Event('change'));")
    view.js("v.q('input').value = 'abc'; v.q('input').dispatchEvent(new Event('change'));")

    assert [s["value"] for s in view.saved()] == [0.0025]


def test_float_field_formats_extreme_values_in_exponent_notation(mount):
    view = mount(FloatField(value=1e-6, min=0.0))

    assert view.js("return v.q('input').value;") == "1e-6"
    assert view.js("return [v.q('input').min, v.q('input').hasAttribute('max')];") == ["0", False]

    view.js("v.change('value', 12.5); v.change('max', 20);")
    assert view.js("return [v.q('input').value, v.q('input').max];") == ["12.5", "20"]


def test_field_view_marks_invalid_inputs_for_assistive_tech(mount):
    view = mount(FloatField(value=1.0))

    view.js("v.change('error', 'bad');")

    assert view.js("return v.q('input').getAttribute('aria-invalid');") == "true"


def test_unit_renders_typeset_and_follows_changes(mount):
    view = mount(FloatField(units=UNIT))

    assert view.js("return v.q('.cadetgui-field-unit').innerHTML;") == "m<sup>3</sup>/s"

    view.js("v.change('units', '');")
    assert view.js("return v.q('.cadetgui-field-unit').hidden;") is True


def test_text_and_bool_views_commit_user_edits(mount):
    view = mount(TextField(value="a"))
    view.js("v.q('input').value = 'b'; v.q('input').dispatchEvent(new Event('change'));")
    assert view.saved()[-1]["value"] == "b"

    view = mount(BoolField(value=False))
    view.js("v.q('input').checked = true; v.q('input').dispatchEvent(new Event('change'));")
    assert view.saved()[-1]["value"] is True

    view.js("v.change('value', false);")
    assert view.js("return v.q('input').checked;") is False


def test_choice_view_lists_options_and_commits_the_selected_index(mount):
    view = mount(ChoiceField(options=[("A", 1), ("B", 2)], value=2))

    assert view.js("return v.qa('option').map((o) => o.textContent);") == ["A", "B"]
    assert view.js("return v.q('select').value;") == "1"

    view.js("v.q('select').value = '0'; v.q('select').dispatchEvent(new Event('change'));")
    assert view.saved()[-1]["selected_index"] == 0

    view.js("v.change('option_labels', ['X']); v.change('selected_index', null);")
    assert view.js("return [v.qa('option').length, v.q('select').value];") == [1, ""]


def test_component_list_view_adds_renames_and_removes_down_to_the_minimum(mount):
    view = mount(ComponentListField(value=["Salt"]))
    assert view.text(".cadetgui-field-count") == "1 component"
    assert view.js("return v.q('.cadetgui-field-list-remove').disabled;") is True

    view.js("v.q('.cadetgui-field-list-add').click();")
    assert view.saved()[-1]["value"] == ["Salt", "Component 2"]
    assert view.text(".cadetgui-field-count") == "2 components"

    view.js("v.qa('input')[0].value = 'NaCl'; v.qa('input')[0].dispatchEvent(new Event('change'));")
    assert view.saved()[-1]["value"] == ["NaCl", "Component 2"]

    view.js("v.qa('.cadetgui-field-list-remove')[1].click();")
    assert view.saved()[-1]["value"] == ["NaCl"]

    view.js("v.change('min_components', 2); v.change('value', ['a', 'b']);")
    view.js("v.q('.cadetgui-field-list-remove').click();")
    assert view.js("return v.qa('input').length;") == 2


def test_free_float_list_view_adds_and_removes_rows(mount):
    view = mount(FloatListField(value=[1.0], units=UNIT))
    assert view.js("return v.q('.cadetgui-field-list-add').hidden;") is False

    view.js("v.q('.cadetgui-field-list-add').click();")
    assert view.saved()[-1]["value"] == [1.0, 0.0]
    assert view.js("return v.qa('.cadetgui-field-unit').length;") == 2

    view.js("v.qa('.cadetgui-field-list-row button')[0].click();")
    assert view.saved()[-1]["value"] == [0.0]


def test_pinned_float_list_view_has_one_named_row_per_component_and_no_editing(mount):
    view = mount(FloatListField(value=[1.0, 2.0], component_names=["Salt", "Protein"]))

    assert view.js("return v.qa('.cadetgui-field-component-name').map((n) => n.textContent);") == [
        "Salt",
        "Protein",
    ]
    assert view.js("return v.q('.cadetgui-field-list-add').hidden;") is True
    assert view.js("return v.qa('.cadetgui-field-list-row button').length;") == 0

    view.js("v.change('component_names', ['Salt']); v.change('value', [1.0]);")
    assert view.js("return v.qa('.cadetgui-field-component-name').length;") == 0


def test_float_list_view_keeps_rows_disabled_after_a_rebuild(mount):
    view = mount(FloatListField(value=[1.0]))
    view.js("v.change('disabled', true); v.change('value', [1.0, 2.0]);")

    assert view.js("return v.qa('input').every((i) => i.disabled);") is True


def test_selectable_table_click_and_arrow_keys_select_rows_with_chips(mount):
    table = SelectableTable(
        columns=["Name", "State"],
        options=[("a", 1), ("b", 2), ("c", 3)],
        rows=[["a", ("ok", "ok")], ["b", ("bad", "error")], ["c", "-"]],
    )
    view = mount(table)
    assert view.js("return v.qa('th').map((t) => t.textContent);") == ["Name", "State"]
    assert view.js("return v.qa('.cadetgui-chip').map((c) => c.className);") == [
        "cadetgui-chip cadetgui-chip-ok",
        "cadetgui-chip cadetgui-chip-error",
    ]
    assert view.js("return v.qa('tbody tr')[0].classList.contains('is-selected');") is True

    view.js("v.qa('tbody tr')[2].click();")
    assert view.saved()[-1]["selected_index"] == 2

    view.js(
        "v.qa('tbody tr')[2].dispatchEvent("
        "new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));"
    )
    assert view.saved()[-1]["selected_index"] == 1

    view.js("v.change('selected_index', 0);")
    assert view.js("return v.qa('tbody tr').map((r) => r.getAttribute('aria-selected'));") == [
        "true",
        "false",
        "false",
    ]


def test_selectable_table_without_rows_shows_the_empty_text(mount):
    view = mount(SelectableTable(empty_text="Nothing yet"))

    assert view.text(".cadetgui-table-empty") == "Nothing yet"


SERIES = [
    {"name": "s1", "times": [0, 1, 2, 3], "values": [0, 1, 4, 2]},
    {"name": "s2", "times": [0, 3], "values": [2, 3], "dashed": True, "reference": True},
]


def test_line_chart_draws_a_line_and_legend_entry_per_series_and_toggles_them(mount):
    view = mount(LineChart(series=SERIES, y_label=UNIT))
    assert view.js("return v.qa('.cadetgui-chart-line').length;") == 2
    assert view.js("return v.qa('.cadetgui-chart-legend-item').length;") == 2
    assert view.js("return v.qa('.cadetgui-chart-line')[1].hasAttribute('stroke-dasharray');")

    view.js("v.q('.cadetgui-chart-legend-item').click();")

    assert view.js("return v.qa('.cadetgui-chart-line').length;") == 1
    assert view.js("return v.q('.cadetgui-chart-legend-item').classList.contains('is-off');")


def test_line_chart_typesets_the_y_label_units(mount):
    view = mount(LineChart(series=SERIES, y_label="Flow / " + UNIT))

    titles = view.js("return v.qa('.cadetgui-chart-axistitle').map((t) => t.textContent);")

    assert "Flow / m3/s" in titles


def test_line_chart_without_series_shows_the_empty_text(mount):
    view = mount(LineChart(empty_text="No data here"))

    assert view.text(".cadetgui-chart-empty") == "No data here"


def test_event_chart_draws_phase_bands_edges_labels_and_markers(mount):
    chart = EventTimelineChart(
        series=[{"name": "f", "times": [0, 5, 10], "values": [0, 1, 1]}],
        phases=[
            {"name": "Load", "start": 0, "end": 4},
            {"name": "Wash", "start": 4, "end": 10},
        ],
        markers=[{"name": "Inject", "time": 6}],
    )
    view = mount(chart)

    assert view.js("return v.qa('.cadetgui-chart-phase-band').length;") == 1
    assert view.js("return v.qa('.cadetgui-chart-phase-edge').length;") == 1
    labels = view.js("return v.qa('.cadetgui-chart-phase-label').map((t) => t.textContent);")
    assert labels == ["Load", "Wash", "Inject"]
    assert view.js("return v.qa('.cadetgui-chart-marker').length;") == 1


def test_line_chart_hover_tooltip_lists_every_visible_series_at_the_cursor_time(mount):
    view = mount(LineChart(series=SERIES))

    view.js(
        """const rect = v.qa('svg rect').slice(-1)[0];
        const box = v.q('svg').getBoundingClientRect();
        rect.dispatchEvent(new PointerEvent('pointermove', {
          clientX: box.left + box.width * 0.5, clientY: box.top + 60, bubbles: true }));"""
    )

    assert view.js("return v.q('.cadetgui-chart-tooltip').hidden;") is False
    names = view.js("return v.qa('.cadetgui-chart-tooltip-name').map((n) => n.textContent);")
    assert names == ["s1", "s2"]
    assert view.text(".cadetgui-chart-tooltip-time").startswith("t = ")


def test_line_chart_drag_zoom_shows_reset_and_reset_restores_the_full_range(mount):
    view = mount(LineChart(series=SERIES))
    assert view.js("return v.q('.cadetgui-chart-reset').hidden;") is True
    full_ticks = view.js("return v.qa('.cadetgui-chart-axislabel').length;")

    view.js(
        """const rect = v.qa('svg rect').slice(-1)[0];
        const box = v.q('svg').getBoundingClientRect();
        const at = (f, type) => rect.dispatchEvent(new PointerEvent(type, {
          clientX: box.left + box.width * f, clientY: box.top + 60,
          pointerId: 1, bubbles: true }));
        at(0.3, 'pointerdown'); at(0.6, 'pointermove'); at(0.6, 'pointerup');"""
    )
    assert view.js("return v.q('.cadetgui-chart-reset').hidden;") is False
    assert view.js("return v.qa('.cadetgui-chart-axislabel').length;") != full_ticks

    view.js("v.q('.cadetgui-chart-reset').click();")
    assert view.js("return v.q('.cadetgui-chart-reset').hidden;") is True
    assert view.js("return v.qa('.cadetgui-chart-axislabel').length;") == full_ticks
