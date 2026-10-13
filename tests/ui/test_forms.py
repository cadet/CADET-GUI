"""FormRenderer: ModelSpec -> elements -> validated, committed build."""

from __future__ import annotations

import ipywidgets as W
import pytest
from cadetgui.parameters import build_parameter_config_spec
from cadetgui.parameters.specs import FieldSpec, ModelSpec, require_positive
from cadetgui.widgets.elements import (
    BoolField,
    ChoiceField,
    FloatField,
    FloatListField,
    TextField,
)
from cadetgui.widgets.forms import FormRenderer, element_for_field
from CADETProcess.processModel import ComponentSystem, Langmuir

DEFAULTS = {"rate": 1.0, "name": "col", "active": True, "levels": [1.0, 2.0]}


def make_spec(build=dict) -> ModelSpec:
    return ModelSpec(
        title="Test",
        fields=[
            FieldSpec("rate", "float", "Rate", default=1.0, min=0.0, validate=require_positive),
            FieldSpec("name", "text", "Name", default="col"),
            FieldSpec("active", "bool", "Active", default=True),
            FieldSpec("levels", "float_list", "Levels", default=[1.0, 2.0]),
        ],
        build=build,
    )


@pytest.fixture
def events():
    return {"built": [], "invalid": []}


@pytest.fixture
def form(events):
    return FormRenderer(
        make_spec(), on_built=events["built"].append, on_invalid=events["invalid"].append
    )


def _reset_button(form: FormRenderer) -> W.Button:
    return next(c for c in form.root.children if isinstance(c, W.Button))


@pytest.mark.parametrize(
    "field, element_type",
    [
        (FieldSpec("r", "float", "R", default=1.0, min=0.0, max=2.0, units="m"), FloatField),
        (FieldSpec("n", "text", default="x"), TextField),
        (FieldSpec("a", "bool", default=True), BoolField),
        (FieldSpec("l", "float_list", default=[1.0], component_names=("Salt",)), FloatListField),
        (FieldSpec("c", "choice", default=2, options=(("A", 1), ("B", 2))), ChoiceField),
    ],
    ids=lambda f: getattr(f, "kind", None),
)
def test_element_for_field_maps_each_kind(field, element_type):
    element = element_for_field(field)

    assert isinstance(element, element_type)
    assert element.value == field.default
    assert element.label == (field.label or field.name)
    if field.kind == "float":
        assert (element.min, element.max, element.units) == (0.0, 2.0, "m")
    if field.component_names:
        assert element.component_names == list(field.component_names)


def test_element_for_field_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="weird"):
        element_for_field(FieldSpec("x", "weird"))


def test_form_builds_from_the_defaults_and_rebuilds_on_every_valid_change(form, events):
    assert form.is_valid and form.built == DEFAULTS == events["built"][0]
    assert form.status.value == ""

    form.element("rate").value = 5.0

    assert form.built == events["built"][-1] == {**DEFAULTS, "rate": 5.0}


def test_form_blocks_the_build_while_invalid_and_recovers(form, events):
    form.element("rate").value = -1.0

    assert not form.is_valid and form.built is None
    assert events["invalid"] == ["Rate: Must be > 0."]
    assert form.status.value

    form.element("rate").value = 2.0
    assert form.built == {**DEFAULTS, "rate": 2.0}
    assert form.status.value == ""


def test_form_reports_a_build_exception_without_raising():
    def failing_build(values):
        raise RuntimeError("boom")

    form = FormRenderer(make_spec(build=failing_build))

    assert form.built is None
    assert "boom" in form.status.value


def test_collect_values_applies_each_fields_transform():
    spec = ModelSpec(
        title="T",
        fields=[FieldSpec("minutes", "float", default=2.0, transform=lambda m: m * 60)],
        build=dict,
    )
    assert FormRenderer(spec).collect_values() == {"minutes": 120.0}


def test_set_values_commits_once_and_reset_restores_the_defaults(form, events):
    form.element("name").value = "old"
    events["built"].clear()

    form.set_values({"rate": 3.0, "active": False})
    assert events["built"] == [{**DEFAULTS, "rate": 3.0, "active": False}]

    _reset_button(form).click()
    assert form.collect_values() == form.default_values() == DEFAULTS


def test_set_disabled_greys_out_fields_and_reset_and_keeps_values(form):
    form.set_values({"rate": 3.0})
    before, built = form.collect_values(), form.built

    form.set_disabled(True)
    assert all(form.element(f.name).disabled for f in form.spec.fields)
    assert _reset_button(form).disabled
    assert (form.collect_values(), form.built) == (before, built)

    form.set_disabled(False)
    assert not any(form.element(f.name).disabled for f in form.spec.fields)


def test_form_commits_edits_to_a_cadet_process_object():
    binding = Langmuir(ComponentSystem(["Salt", "Protein"]), name="binding")
    form = FormRenderer(build_parameter_config_spec(binding))

    form.element("capacity").value = [10.0, 20.0]
    form.element("is_kinetic").value = False

    assert form.built is binding
    assert binding.capacity == [10.0, 20.0]
    assert binding.is_kinetic is False
