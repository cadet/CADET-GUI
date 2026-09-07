from __future__ import annotations

import pytest
from cadetgui.widgets.elements import (
    BoolField,
    ChoiceField,
    ComponentListField,
    Element,
    FloatField,
    FloatListField,
    TextField,
)


def test_floatfield_value_and_label():
    f = FloatField(label="Flow rate", value=1.5)
    assert f.value == pytest.approx(1.5)
    assert f.label == "Flow rate"
    assert f.is_valid


def test_floatfield_bounds_default_to_unbounded():
    f = FloatField(label="x")
    assert f.min is None
    assert f.max is None


def test_floatfield_validate_runs_on_change():
    def positive(v):
        if v <= 0:
            return "must be > 0"

    f = FloatField(value=1.0, validate=positive)
    assert f.is_valid

    f.value = -1.0
    assert not f.is_valid
    assert f.error == "must be > 0"

    f.value = 2.0
    assert f.is_valid


def test_floatfield_observe_fires_on_value_change():
    f = FloatField(value=0.0)
    seen = []
    f.observe(lambda change: seen.append(change["new"]), names="value")
    f.value = 5.0
    assert seen == [5.0]


def test_floatfield_is_element():
    assert isinstance(FloatField(), Element)


def test_floatfield_ships_esm_and_css():
    f = FloatField()
    assert "function render" in f._esm
    assert ".cadetgui-field" in f._css


def test_textfield_get_set():
    t = TextField(label="Name", value="Alice")
    assert t.value == "Alice"
    t.value = "Bob"
    assert t.value == "Bob"


def test_boolfield_get_set():
    b = BoolField(label="Flag", value=False)
    assert b.value is False
    b.value = True
    assert b.value is True


def test_floatlistfield_defaults_and_set():
    fl = FloatListField(label="Feed")
    assert fl.value == [0.0]

    fl2 = FloatListField(value=[1.0, 2.5, 3])
    assert fl2.value == [1.0, 2.5, 3.0]

    fl2.value = [4.0]
    assert fl2.value == [4.0]


def test_choicefield_selects_by_value_and_tracks_index():
    col_a, col_b = object(), object()
    c = ChoiceField(label="Column", options=[("GRM", col_a), ("LRMP", col_b)], value=col_b)
    assert c.value is col_b
    assert c.selected_index == 1
    assert c.option_labels == ["GRM", "LRMP"]


def test_choicefield_defaults_to_first_option():
    c = ChoiceField(options=[("A", 1), ("B", 2)])
    assert c.value == 1
    assert c.selected_index == 0


def test_choicefield_set_value_updates_index():
    c = ChoiceField(options=[("A", 1), ("B", 2)], value=1)
    c.value = 2
    assert c.selected_index == 1


def test_choicefield_set_options_keeps_matching_value():
    c = ChoiceField(options=[("A", 1), ("B", 2)], value=2)
    c.set_options([("B", 2), ("C", 3)])
    assert c.value == 2
    assert c.selected_index == 0


def test_choicefield_validate_observes_selected_index():
    def not_none(v):
        if v is None:
            return "required"

    c = ChoiceField(options=[("A", 1)], value=1, validate=not_none)
    assert c.is_valid

    c.set_options([])
    assert not c.is_valid
    assert c.error == "required"


def test_componentlistfield_defaults_to_one_component():
    f = ComponentListField(label="Components:")
    assert f.value == ["Component 1"]


def test_componentlistfield_accepts_initial_names():
    f = ComponentListField(value=["Salt", "Protein"])
    assert f.value == ["Salt", "Protein"]


def test_componentlistfield_empty_initial_value_falls_back_to_default():
    f = ComponentListField(value=[])
    assert f.value == ["Component 1"]


def test_componentlistfield_observe_fires_on_value_change():
    f = ComponentListField()
    seen = []
    f.observe(lambda change: seen.append(change["new"]), names="value")
    f.value = ["A", "B", "C"]
    assert seen == [["A", "B", "C"]]
