from __future__ import annotations

from cadetgui.cadetprocessadapter import FieldSpec, ModelSpec, require_positive
from cadetgui.widgets.forms import FormRenderer, element_for_field


def make_spec() -> ModelSpec:
    def build(values):
        return dict(values)

    fields = [
        FieldSpec("rate", "float", "Rate", default=1.0, min=0.0, validate=require_positive),
        FieldSpec("name", "text", "Name", default="col"),
        FieldSpec("active", "bool", "Active", default=True),
        FieldSpec("levels", "float_list", "Levels", default=[1.0, 2.0]),
    ]
    return ModelSpec(title="Test", fields=fields, build=build)


def test_element_for_field_maps_kind_to_element_type():
    from cadetgui.widgets.elements import (
        BoolField,
        FloatField,
        FloatListField,
        TextField,
    )

    assert isinstance(element_for_field(FieldSpec("r", "float", default=1.0)), FloatField)
    assert isinstance(element_for_field(FieldSpec("n", "text", default="x")), TextField)
    assert isinstance(element_for_field(FieldSpec("a", "bool", default=True)), BoolField)
    field = FieldSpec("l", "float_list", default=[1.0])
    assert isinstance(element_for_field(field), FloatListField)


def test_element_for_field_passes_units_through_to_the_element():
    field = FieldSpec("length", "float", "Length", default=0.5, units="m")
    element = element_for_field(field)
    assert element.units == "m"

    unitless = element_for_field(FieldSpec("rate", "float", default=1.0))
    assert unitless.units == ""


def test_element_for_field_passes_component_names_through_to_float_list():
    field = FieldSpec("rate", "float_list", default=[1.0, 2.0], component_names=("Salt", "Protein"))
    element = element_for_field(field)
    assert element.component_names == ["Salt", "Protein"]

    unnamed = element_for_field(FieldSpec("rate", "float_list", default=[1.0]))
    assert unnamed.component_names == []


def test_form_renders_one_element_per_field_with_defaults():
    form = FormRenderer(make_spec())
    assert set(form._elements) == {"rate", "name", "active", "levels"}
    assert form._elements["rate"].value == 1.0
    assert form._elements["name"].value == "col"
    assert form._elements["active"].value is True
    assert form._elements["levels"].value == [1.0, 2.0]
    assert form.is_valid


def test_form_builds_object_from_defaults_on_construction():
    form = FormRenderer(make_spec())
    assert form.built == {"rate": 1.0, "name": "col", "active": True, "levels": [1.0, 2.0]}
    assert form.status.value == ""


def test_form_auto_commits_on_a_valid_field_change():
    form = FormRenderer(make_spec())
    form._elements["rate"].value = 5.0
    assert form.built == {"rate": 5.0, "name": "col", "active": True, "levels": [1.0, 2.0]}
    assert form.status.value == ""


def test_form_commit_blocked_when_a_field_is_invalid():
    form = FormRenderer(make_spec())
    form._elements["rate"].value = -1.0
    assert not form.is_valid
    assert form.built is None
    assert "invalid" in form.status.value.lower() or "fix" in form.status.value.lower()


def test_form_reset_restores_defaults():
    form = FormRenderer(make_spec())
    form._elements["rate"].value = 99.0
    form._elements["active"].value = False

    form._on_reset(None)
    assert form._elements["rate"].value == 1.0
    assert form._elements["active"].value is True


def test_form_reports_build_exception_without_raising():
    def failing_build(values):
        raise RuntimeError("boom")

    fields = [FieldSpec("x", "float", default=1.0)]
    spec = ModelSpec(title="Fail", fields=fields, build=failing_build)
    form = FormRenderer(spec)
    assert form.built is None
    assert "boom" in form.status.value
