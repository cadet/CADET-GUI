"""Element contract (value, validate, error, units) in Python and in the JS views."""

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

UNIT = r"\frac{\mathrm{m}^{3}}{\mathrm{s}}"

# (class, constructor kwargs, a valid value, an invalid value)
ELEMENTS = [
    (FloatField, {}, 2.0, -1.0),
    (TextField, {}, "ok", ""),
    (BoolField, {}, True, False),
    (FloatListField, {}, [1.0, 2.0], [-1.0]),
    (ComponentListField, {}, ["Salt"], ["Salt", "Salt"]),
    (ChoiceField, {"options": [("A", 1), ("B", 2)]}, 1, 2),
    (SelectableTable, {"options": [("A", 1), ("B", 2)]}, 1, 2),
]
HAS_UNITS = (FloatField, TextField, BoolField, FloatListField)


def _validator(bad, style):
    def validate(value):
        if value == bad:
            if style == "raise":
                raise ValueError("not allowed")
            return "not allowed"

    return validate


@pytest.mark.parametrize("style", ["message", "raise"])
@pytest.mark.parametrize("cls, kwargs, good, bad", ELEMENTS, ids=[e[0].__name__ for e in ELEMENTS])
def test_element_validates_at_construction_and_on_every_change(cls, kwargs, good, bad, style):
    element = cls(**kwargs, value=bad, validate=_validator(bad, style))
    assert element.value == bad
    assert (element.is_valid, element.error) == (False, "not allowed")

    element.value = good
    assert element.value == good
    assert (element.is_valid, element.error) == (True, "")

    element.value = bad
    assert not element.is_valid


@pytest.mark.parametrize("cls", HAS_UNITS, ids=lambda c: c.__name__)
def test_element_carries_label_and_units(cls):
    element = cls(label="Flow", units=UNIT)
    assert (element.label, element.units) == ("Flow", UNIT)
    assert cls().units == ""


@pytest.mark.parametrize(
    "value, names, expected",
    [
        (None, [], [0.0]),
        ([1, 2.5], [], [1.0, 2.5]),
        ([1.0], ["Salt", "Protein", "Impurity"], [1.0, 0.0, 0.0]),
        ([1.0, 2.0, 3.0], ["Salt"], [1.0]),
    ],
)
def test_float_list_is_sized_to_its_components(value, names, expected):
    assert FloatListField(value=value, component_names=names).value == expected


@pytest.mark.parametrize("given", [None, []])
def test_component_list_defaults_to_one_component(given):
    assert ComponentListField(value=given).value == ["Component 1"]
    assert ComponentListField(value=given, blank_rows=True).value == []


@pytest.mark.parametrize(
    "new_options, select_none, expected_index, expected_value",
    [
        ([("B", 2), ("C", 3)], False, 0, 2),
        ([("C", 3), ("D", 4)], False, 0, 3),
        ([("A", 1), ("B", 2)], True, None, None),
        ([], False, None, None),
    ],
)
@pytest.mark.parametrize("cls", [ChoiceField, SelectableTable], ids=lambda c: c.__name__)
def test_set_options_keeps_falls_back_or_clears_the_selection(
    cls, new_options, select_none, expected_index, expected_value
):
    choice = cls(options=[("A", 1), ("B", 2)], value=2)

    choice.set_options(new_options, select_none=select_none)

    assert (choice.selected_index, choice.value) == (expected_index, expected_value)
    assert choice.option_labels == [label for label, _ in new_options]


def test_choice_defaults_to_the_first_option_and_holds_any_object():
    a, b = object(), object()
    assert ChoiceField(options=[("A", a), ("B", b)]).value is a
    assert ChoiceField().value is None


def test_selectable_table_normalises_rows_and_rejects_a_length_mismatch():
    table = SelectableTable(
        columns=["Name", "State"],
        options=[("a", 1), ("b", 2)],
        rows=[["a", ("ok", "ok")], ["b", "-"]],
    )
    assert table.rows == [
        [{"text": "a"}, {"text": "ok", "chip": "ok"}],
        [{"text": "b"}, {"text": "-"}],
    ]
    assert SelectableTable(options=[("only", 0)]).rows == [[{"text": "only"}]]

    with pytest.raises(ValueError, match="2 rows for 1 options"):
        table.set_options([("a", 1)], rows=[["A"], ["B"]])


# --- JS views (headless Chromium; skipped without it) ---

VIEWS = [
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
]


@pytest.mark.parametrize("widget", VIEWS, ids=lambda w: type(w).__name__)
def test_every_view_renders_its_default_state(mount, widget):
    assert mount(widget).js("return v.el.children.length;") == 1


@pytest.mark.parametrize(
    "widget",
    [
        FloatField(label="Flow", units=UNIT),
        TextField(label="Flow", units=UNIT),
        BoolField(label="Flow", units=UNIT),
        ChoiceField(label="Flow", options=[("A", 1)]),
    ],
    ids=lambda w: type(w).__name__,
)
def test_field_views_show_label_units_error_and_disabled_state(mount, widget):
    view = mount(widget)
    assert view.text(".cadetgui-field-label") == "Flow"
    if widget.units:
        assert view.js("return v.q('.cadetgui-field-unit').innerHTML;") == "m<sup>3</sup>/s"
    assert view.js("return v.q('.cadetgui-field-error').hidden;") is True

    view.js("v.change('error', 'too big'); v.change('disabled', true);")
    assert view.text(".cadetgui-field-error") == "too big"
    assert view.js("return v.q('.cadetgui-field-error').hidden;") is False
    assert view.js("return v.qa('input, select').every((n) => n.disabled);") is True


@pytest.mark.parametrize(
    "widget, edit, key, expected",
    [
        (FloatField(value=1.0), "v.q('input').value = '2.5e-3'", "value", 0.0025),
        (TextField(value="a"), "v.q('input').value = 'b'", "value", "b"),
        (BoolField(value=False), "v.q('input').checked = true", "value", True),
        (
            ChoiceField(options=[("A", 1), ("B", 2)], value=2),
            "v.q('select').value = '0'",
            "selected_index",
            0,
        ),
    ],
    ids=["FloatField", "TextField", "BoolField", "ChoiceField"],
)
def test_field_views_commit_user_edits(mount, widget, edit, key, expected):
    view = mount(widget)
    tag = "select" if key == "selected_index" else "input"
    view.js(f"{edit}; v.q('{tag}').dispatchEvent(new Event('change'));")
    assert view.last_saved()[key] == expected


def test_compact_text_view_is_as_wide_as_its_content(mount):
    view = mount(TextField(value="1", compact=True))
    assert view.js("return v.q('input').classList.contains('cadetgui-field-input-compact');")
    short = view.js("return v.q('input').size;")
    view.js("v.change('value', '1.5e-7, 2.5e-7, 3.5e-7');")
    assert view.js("return v.q('input').size;") > short


def test_float_view_ignores_unparseable_input(mount):
    view = mount(FloatField(value=1.0))
    view.js("v.q('input').value = 'abc'; v.q('input').dispatchEvent(new Event('change'));")
    assert view.js("return v.saved.length;") == 0


def test_component_list_view_adds_renames_and_removes_down_to_the_minimum(mount):
    view = mount(ComponentListField(value=["Salt"]))
    assert view.js("return v.q('.cadetgui-field-list-remove').disabled;") is True

    view.js("v.q('.cadetgui-field-list-add').click();")
    assert view.last_saved()["value"] == ["Salt", "Component 2"]

    view.js("v.qa('input')[0].value = 'NaCl'; v.qa('input')[0].dispatchEvent(new Event('change'));")
    view.js("v.qa('.cadetgui-field-list-remove')[1].click();")
    assert view.last_saved()["value"] == ["NaCl"]


def test_float_list_view_is_free_or_pinned_to_components(mount):
    view = mount(FloatListField(value=[1.0]))
    view.js("v.q('.cadetgui-field-list-add').click();")
    assert view.last_saved()["value"] == [1.0, 0.0]

    view = mount(FloatListField(value=[1.0, 2.0], component_names=["Salt", "Protein"]))
    names = view.js("return v.qa('.cadetgui-field-component-name').map((n) => n.textContent);")
    assert names == ["Salt", "Protein"]
    assert view.js("return v.q('.cadetgui-field-list-add').hidden;") is True


def test_selectable_table_view_selects_by_click_and_arrow_keys(mount):
    view = mount(SelectableTable(columns=["Name"], options=[("a", 1), ("b", 2), ("c", 3)]))

    view.js("v.qa('tbody tr')[2].click();")
    assert view.last_saved()["selected_index"] == 2
    view.js(
        "v.qa('tbody tr')[2].dispatchEvent("
        "new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));"
    )
    assert view.last_saved()["selected_index"] == 1

    empty = mount(SelectableTable(empty_text="Nothing yet"))
    assert empty.text(".cadetgui-table-empty") == "Nothing yet"


def test_line_chart_draws_toggleable_series_or_the_empty_text(mount):
    series = [
        {"name": "s1", "times": [0, 1, 2], "values": [0, 1, 4]},
        {"name": "s2", "times": [0, 2], "values": [2, 3], "dashed": True},
    ]
    view = mount(LineChart(series=series))
    assert view.js("return v.qa('.cadetgui-chart-line').length;") == 2

    view.js("v.q('.cadetgui-chart-legend-item').click();")
    assert view.js("return v.qa('.cadetgui-chart-line').length;") == 1

    assert mount(LineChart(empty_text="No data")).text(".cadetgui-chart-empty") == "No data"


def test_chart_clipping_ids_are_unique_across_widget_modules(page):
    series = [{"name": "Tracer", "times": [0, 2, 10], "values": [0, 0.3, 1]}]
    widgets = [EventTimelineChart(series=series), ChromatogramChart(series=series)]
    payload = [
        {"esm": widget._esm, "state": widget.get_state()}
        for widget in widgets
    ]
    result = page.evaluate(
        """async (widgets) => {
          document.body.replaceChildren();
          const ids = [];
          const ownsClip = [];
          for (const {esm, state} of widgets) {
            // Each anywidget loads its own module instance in the same document.
            const url = URL.createObjectURL(new Blob([esm], {type: "text/javascript"}));
            const mod = await import(url);
            const el = document.createElement("div");
            document.body.appendChild(el);
            mod.default.render({model: {get: key => state[key], on: () => {}}, el});
            URL.revokeObjectURL(url);
            const id = el.querySelector("clipPath").id;
            ids.push(id);
            ownsClip.push(el.contains(document.getElementById(id)));
          }
          return {ids, ownsClip};
        }""",
        payload,
    )
    assert len(set(result["ids"])) == len(widgets)
    assert all(result["ownsClip"])
