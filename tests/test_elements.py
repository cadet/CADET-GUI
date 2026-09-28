from __future__ import annotations

import pytest
from cadetgui.widgets.elements import (
    ChoiceField,
    ComponentListField,
    FloatField,
    FloatListField,
    SelectableTable,
)


def _positive_message(v):
    if v <= 0:
        return "must be > 0"


def _positive_raises(v):
    if v <= 0:
        raise ValueError("must be > 0")


@pytest.mark.parametrize("validate", [_positive_message, _positive_raises])
def test_validation_runs_at_construction_and_on_every_value_change(validate):
    f = FloatField(value=-1.0, validate=validate)
    assert not f.is_valid
    assert f.error == "must be > 0"

    f.value = 2.0
    assert f.is_valid
    assert f.error == ""

    f.value = 0.0
    assert not f.is_valid


def test_floatlistfield_defaults_to_one_zero_and_coerces_to_float():
    assert FloatListField().value == [0.0]
    assert FloatListField(value=[1, 2.5]).value == [1.0, 2.5]


@pytest.mark.parametrize(
    "value, names, expected",
    [
        ([1.0], ["Salt", "Protein", "Impurity"], [1.0, 0.0, 0.0]),
        ([1.0, 2.0, 3.0], ["Salt"], [1.0]),
        ([1.0, 2.0], ["Salt", "Protein"], [1.0, 2.0]),
        (None, ["Salt", "Protein"], [0.0, 0.0]),
    ],
)
def test_pinned_floatlistfield_sizes_value_to_the_component_count(value, names, expected):
    fl = FloatListField(value=value, component_names=names)

    assert fl.component_names == names
    assert fl.value == expected


def test_choicefield_selects_by_value_and_tracks_index():
    col_a, col_b = object(), object()
    c = ChoiceField(label="Column", options=[("GRM", col_a), ("LRMP", col_b)], value=col_b)
    assert c.value is col_b
    assert c.selected_index == 1
    assert c.option_labels == ["GRM", "LRMP"]

    c.value = col_a
    assert c.selected_index == 0


def test_choicefield_defaults_to_first_option_and_to_none_without_options():
    assert ChoiceField(options=[("A", 1), ("B", 2)]).value == 1
    empty = ChoiceField()
    assert empty.value is None
    assert empty.selected_index is None


def test_choicefield_set_options_keeps_a_value_that_is_still_present():
    c = ChoiceField(options=[("A", 1), ("B", 2)], value=2)

    c.set_options([("B", 2), ("C", 3)])

    assert c.value == 2
    assert c.selected_index == 0


def test_choicefield_set_options_falls_back_to_the_first_option_when_the_value_is_gone():
    c = ChoiceField(options=[("A", 1), ("B", 2)], value=2)

    c.set_options([("C", 3), ("D", 4)])

    assert (c.selected_index, c.value) == (0, 3)


def test_choicefield_set_options_can_leave_nothing_selected():
    c = ChoiceField(options=[("A", 1), ("B", 2)], value=2)

    c.set_options([("A", 1), ("B", 2)], select_none=True)

    assert c.selected_index is None
    assert c.value is None
    assert c.option_labels == ["A", "B"]


def test_choicefield_validates_against_the_selected_index():
    def not_none(v):
        if v is None:
            return "required"

    c = ChoiceField(options=[("A", 1)], value=1, validate=not_none)
    assert c.is_valid

    c.set_options([])
    assert c.error == "required"


@pytest.mark.parametrize("given", [None, []])
def test_componentlistfield_falls_back_to_one_default_component(given):
    assert ComponentListField(value=given).value == ["Component 1"]


def test_componentlistfield_keeps_the_given_names():
    assert ComponentListField(value=["Salt", "Protein"]).value == ["Salt", "Protein"]


def test_selectable_table_is_a_choicefield_with_normalised_rows():
    table = SelectableTable(
        columns=["Name", "State"],
        options=[("a", 1), ("b", 2)],
        rows=[["a", ("ok", "ok")], ["b", ("failed", "error")]],
    )

    assert isinstance(table, ChoiceField)
    assert table.value == 1
    table.selected_index = 1
    assert table.value == 2
    assert table.rows[0] == [{"text": "a"}, {"text": "ok", "chip": "ok"}]
    assert table.rows[1][1] == {"text": "failed", "chip": "error"}


def test_selectable_table_rows_default_to_the_option_labels():
    assert SelectableTable(options=[("only", 0)]).rows == [[{"text": "only"}]]


def test_selectable_table_set_options_replaces_rows_and_rejects_a_length_mismatch():
    table = SelectableTable(columns=["x"])
    table.set_options([("a", 1), ("b", 2)], rows=[["A"], ["B"]])
    assert [r[0]["text"] for r in table.rows] == ["A", "B"]

    with pytest.raises(ValueError, match="2 rows for 1 options"):
        table.set_options([("a", 1)], rows=[["A"], ["B"]])

    table.set_options([])
    assert table.rows == []
    assert table.value is None


def test_selectable_table_select_none_keeps_the_new_rows_selectable_afterwards():
    table = SelectableTable(options=[("a", 1)])

    table.set_options([("a", 1), ("b", 2)], rows=[["A"], ["B"]], select_none=True)

    assert table.selected_index is None
    assert len(table.rows) == 2
    table.selected_index = 1
    assert table.value == 2
