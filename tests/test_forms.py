from __future__ import annotations

import ipywidgets as W
import pytest
from cadetgui.cadetprocessadapter import FieldSpec, ModelSpec, require_positive
from cadetgui.widgets.elements import (
    BoolField,
    ChoiceField,
    FloatField,
    FloatListField,
    TextField,
)
from cadetgui.widgets.forms import FormRenderer, element_for_field

DEFAULTS = {"rate": 1.0, "name": "col", "active": True, "levels": [1.0, 2.0]}


def make_spec(build=dict) -> ModelSpec:
    fields = [
        FieldSpec("rate", "float", "Rate", default=1.0, min=0.0, validate=require_positive),
        FieldSpec("name", "text", "Name", default="col"),
        FieldSpec("active", "bool", "Active", default=True),
        FieldSpec("levels", "float_list", "Levels", default=[1.0, 2.0]),
    ]
    return ModelSpec(title="Test", fields=fields, build=build)


def _reset_button(form: FormRenderer) -> W.Button:
    return next(c for c in form.root.children if isinstance(c, W.Button))


@pytest.mark.parametrize(
    "field, element_type",
    [
        (FieldSpec("r", "float", default=1.0), FloatField),
        (FieldSpec("n", "text", default="x"), TextField),
        (FieldSpec("a", "bool", default=True), BoolField),
        (FieldSpec("l", "float_list", default=[1.0]), FloatListField),
        (FieldSpec("c", "choice", default=2, options=(("A", 1), ("B", 2))), ChoiceField),
    ],
)
def test_element_for_field_maps_kind_to_element_type_and_default(field, element_type):
    element = element_for_field(field)

    assert isinstance(element, element_type)
    assert element.value == field.default


def test_element_for_field_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="weird"):
        element_for_field(FieldSpec("x", "weird"))


def test_element_for_field_carries_label_bounds_units_and_component_names():
    element = element_for_field(
        FieldSpec("length", "float", "Length", default=0.5, min=0.0, max=2.0, units="m")
    )
    assert (element.label, element.min, element.max, element.units) == ("Length", 0.0, 2.0, "m")

    unlabeled = element_for_field(FieldSpec("rate", "float", default=1.0))
    assert (unlabeled.label, unlabeled.units) == ("rate", "")

    per_component = element_for_field(
        FieldSpec("q", "float_list", default=[1.0, 2.0], component_names=("Salt", "Protein"))
    )
    assert per_component.component_names == ["Salt", "Protein"]


def test_element_for_field_wires_the_field_validator_to_the_element():
    element = element_for_field(FieldSpec("r", "float", default=1.0, validate=require_positive))

    element.value = -1.0

    assert element.error


def test_form_renders_one_element_per_field_and_builds_from_the_defaults():
    form = FormRenderer(make_spec())

    assert {name: form.element(name).value for name in DEFAULTS} == DEFAULTS
    assert form.is_valid
    assert form.built == DEFAULTS
    assert form.status.value == ""


def test_form_rebuilds_on_every_valid_field_change():
    form = FormRenderer(make_spec())

    form.element("rate").value = 5.0

    assert form.built == {**DEFAULTS, "rate": 5.0}


def test_form_blocks_the_build_while_a_field_is_invalid_and_recovers():
    form = FormRenderer(make_spec())

    form.element("rate").value = -1.0

    assert not form.is_valid
    assert form.built is None
    assert "Fix the highlighted field" in form.status.value

    form.element("rate").value = 2.0
    assert form.built == {**DEFAULTS, "rate": 2.0}
    assert form.status.value == ""


def test_form_reports_build_exception_without_raising():
    def failing_build(values):
        raise RuntimeError("boom")

    form = FormRenderer(make_spec(build=failing_build))

    assert form.built is None
    assert "boom" in form.status.value


def test_form_notifies_listeners_of_builds_and_of_the_first_error():
    built, invalid = [], []
    form = FormRenderer(make_spec(), on_built=built.append, on_invalid=invalid.append)
    assert built == [DEFAULTS]

    form.element("rate").value = -1.0

    assert len(built) == 1
    assert invalid == ["Rate: Must be > 0."]


def test_collect_values_applies_each_fields_transform():
    spec = ModelSpec(
        title="T",
        fields=[FieldSpec("minutes", "float", default=2.0, transform=lambda m: m * 60)],
        build=dict,
    )

    assert FormRenderer(spec).collect_values() == {"minutes": 120.0}


def test_form_reset_restores_defaults():
    form = FormRenderer(make_spec())
    form.element("rate").value = 99.0
    form.element("active").value = False

    _reset_button(form).click()

    assert form.collect_values() == DEFAULTS


def test_set_values_commits_once_and_resets_fields_it_omits():
    built = []
    form = FormRenderer(make_spec(), on_built=built.append)
    form.element("name").value = "old"
    built.clear()

    form.set_values({"rate": 3.0, "active": False})

    assert built == [{"rate": 3.0, "name": "col", "active": False, "levels": [1.0, 2.0]}]


def test_set_disabled_greys_out_every_field_and_the_reset_button_and_keeps_values():
    form = FormRenderer(make_spec())
    form.set_values({"rate": 3.0, "name": "x", "active": False, "levels": [4.0]})
    before, built = form.collect_values(), form.built
    elements = [form.element(f.name) for f in form.spec.fields]

    form.set_disabled(True)
    assert all(e.disabled for e in elements)
    assert _reset_button(form).disabled
    assert form.collect_values() == before
    assert form.built is built

    form.set_disabled(False)
    assert not any(e.disabled for e in elements)
    assert not _reset_button(form).disabled
