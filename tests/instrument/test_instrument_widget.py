"""InstrumentWidget: the LC-system flow sheet, its unit forms, validation and state."""
from __future__ import annotations

import pytest
from cadetgui.instrument.system import BYPASSABLE_UNITS, CONFIGURABLE_UNITS
from cadetgui.widgets.instrument import InstrumentWidget


def unit_names(iw):
    return [u.name for u in iw.flow_sheet.units]


@pytest.fixture
def full():
    """An InstrumentWidget with every unit and the sample loop in the flow path."""
    iw = InstrumentWidget()
    for checkbox in iw._unit_checkboxes.values():
        checkbox.value = True
    iw._sample_loop_checkbox.value = True
    return iw


def test_default_builds_a_column_only_flow_sheet_and_notifies_on_rebuilds():
    iw = InstrumentWidget()
    seen = []
    iw.add_listener(seen.append)

    assert iw.flow_sheet is not None
    assert set(iw.bypass_units()) == set(BYPASSABLE_UNITS) - {"column"}
    assert "sample_loop" not in unit_names(iw)

    iw.components = ["Salt", "Protein"]
    assert seen == [iw.flow_sheet]
    assert iw.flow_sheet.component_system.names == ["Salt", "Protein"]
    assert iw._components_field.value == ["Salt", "Protein"]


def test_every_configurable_unit_gets_a_form_that_edits_the_flow_sheet(full):
    assert set(full._unit_forms) == set(CONFIGURABLE_UNITS)
    sheet = full.flow_sheet

    full._unit_forms["mixer"].element("init_liquid_volume").value = 5e-5
    full._unit_forms["tubing_pre_column"].element("length").value = 0.33
    full._sample_loop_checkbox.value = False

    assert full.flow_sheet is not sheet
    assert full.flow_sheet.mixer.init_liquid_volume == 5e-5
    assert full.flow_sheet.tubing_pre_column.length == 0.33


@pytest.mark.parametrize("unit", [u for u in BYPASSABLE_UNITS if u != "mixer"])
def test_unchecking_a_unit_removes_it_and_its_form(full, unit):
    full._unit_checkboxes[unit].value = False

    assert unit not in unit_names(full)
    assert unit not in full._unit_forms
    assert unit in full.bypass_units()


def test_a_bypassed_mixer_keeps_lcflowsheets_forced_volume_and_its_edit(full):
    full._unit_forms["mixer"].element("init_liquid_volume").value = 5e-5

    full._unit_checkboxes["mixer"].value = False
    assert full.flow_sheet.mixer.init_liquid_volume == 1e-9

    full._unit_checkboxes["mixer"].value = True
    assert full.flow_sheet.mixer.init_liquid_volume == 5e-5


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("_loop_volume_field", 0.0),
        ("_loop_volume_field", float("nan")),
        ("_loop_diameter_field", -1e-3),
        (("mixer", "init_liquid_volume"), 0.0),
        (("tubing_pre_injection", "diameter"), -1e-3),
        (("tubing_detectors", "axial_dispersion"), -1.0),
        (("tubing_post_column", "length"), float("inf")),
    ],
)
def test_invalid_input_withholds_the_flow_sheet_until_fixed(full, field, bad):
    full._loop_diameter_auto_checkbox.value = False
    element = (
        full._unit_forms[field[0]].element(field[1]) if isinstance(field, tuple)
        else getattr(full, field)
    )
    good = element.value
    seen = []
    full.add_listener(seen.append)

    element.value = bad
    assert element.error
    assert full.flow_sheet is None and seen[-1] is None
    assert "Invalid System inputs" in full.status.value

    element.value = good
    assert not element.error
    assert full.flow_sheet is not None and seen[-1] is full.flow_sheet


def test_loop_inputs_only_matter_while_used(full):
    full._loop_diameter_field.value = 0.0
    assert full.flow_sheet is not None

    full._loop_volume_field.value = 0.0
    assert full.flow_sheet is None
    full._sample_loop_checkbox.value = False
    assert full.flow_sheet is not None


def test_zero_axial_dispersion_is_accepted(full):
    full._unit_forms["tubing_detectors"].element("axial_dispersion").value = 0.0
    assert full.flow_sheet is not None


def test_required_sample_loop_is_locked_and_restores_the_users_choice():
    iw = InstrumentWidget()
    seen = []
    iw.set_required_units({"sample_loop"}, reason="Pulse Injection")
    iw.add_listener(seen.append)

    assert iw._sample_loop_checkbox.value and iw._sample_loop_checkbox.disabled
    assert "sample_loop" in unit_names(iw)
    iw.set_required_units({"sample_loop"}, reason="Step Elution")
    assert seen == []

    iw.set_required_units(set())
    assert not iw._sample_loop_checkbox.value and not iw._sample_loop_checkbox.disabled
    with pytest.raises(ValueError):
        iw.set_required_units({"mixer"})


@pytest.mark.parametrize(
    "edit",
    [
        lambda iw: None,
        lambda iw: setattr(iw._unit_checkboxes["column"], "value", False),
        lambda iw: setattr(iw._unit_checkboxes["tubing_pre_column"], "value", True),
    ],
    ids=["default", "no-column", "tubing"],
)
def test_snapshot_and_apply_state_round_trip(full, edit):
    full._unit_forms["mixer"].element("init_liquid_volume").value = 2.5e-5
    full._unit_forms["tubing_detectors"].element("axial_dispersion").value = 3e-8
    full._loop_volume_field.value = 7e-8
    edit(full)
    state = full.snapshot()
    assert isinstance(state.unit_values["tubing_detectors"]["axial_dispersion"], float)

    target = InstrumentWidget()
    target.apply_state(state)

    assert target.snapshot() == state
    assert target.bypass_units() == full.bypass_units()
    assert target.flow_sheet.mixer.init_liquid_volume == 2.5e-5


def test_template_picker_calls_back_only_on_a_user_pick():
    iw = InstrumentWidget()
    picked = []
    iw.set_template_options(["A", "B"], "A", picked.append)
    iw.select_template("B")
    assert picked == []

    iw._template_picker.value = "A"
    assert picked == ["A"]


def test_min_components_and_components_editor():
    iw = InstrumentWidget()
    iw.set_min_components(2, "Needs two.")
    assert iw._components_field.min_components == 2

    editor = InstrumentWidget().root
    iw.set_components_editor(editor)
    assert editor in iw._components_section.children


def test_diagram_follows_highlights_inlets_and_hardware():
    iw = InstrumentWidget()
    before = iw._diagram.root.value
    iw._unit_checkboxes["mixer"].value = True
    after_mixer = iw._diagram.root.value
    assert after_mixer != before

    iw.set_active_inlets(["buffer_a"], {"buffer_a": ["Component 1"]})
    iw.set_highlight({"column"}, observe="outlet")
    assert iw._diagram.root.value != after_mixer
