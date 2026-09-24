from __future__ import annotations

import warnings

import pytest
from cadetgui.widgets.composite import InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)


def _fully_enabled_instrument() -> InstrumentWidget:
    """An InstrumentWidget with every unit checked (by default only "column" is)."""
    iw = InstrumentWidget()
    for checkbox in iw._unit_checkboxes.values():
        checkbox.value = True
    return iw


def _instrument_with_loop() -> InstrumentWidget:
    iw = InstrumentWidget()
    iw._sample_loop_checkbox.value = True
    return iw


def test_configurable_units_get_real_parameter_forms_by_default():
    iw = _fully_enabled_instrument()
    assert set(iw._unit_forms) == {
        "mixer", "tubing_pre_injection", "tubing_pre_column",
        "tubing_post_column", "tubing_detectors",
    }
    assert {f.name for f in iw._unit_forms["mixer"].spec.fields} == {"init_liquid_volume"}
    assert {f.name for f in iw._unit_forms["tubing_pre_column"].spec.fields} == {
        "length", "diameter", "axial_dispersion",
    }


def test_column_has_no_parameter_form_here():
    # ConfigurationWidget owns the column's own parameter form.
    iw = InstrumentWidget()
    assert "column" not in iw._unit_forms
    assert "column" not in iw._unit_form_boxes


def test_editing_a_unit_field_commits_directly_without_a_full_rebuild():
    iw = _fully_enabled_instrument()
    flow_sheet_before = iw.flow_sheet

    iw._unit_forms["mixer"].element("init_liquid_volume").value = 5e-5

    assert iw.flow_sheet is flow_sheet_before  # no LCFlowSheet reconstruction needed
    assert iw.flow_sheet.mixer.init_liquid_volume == 5e-5


def test_unit_field_edit_persists_across_an_unrelated_rebuild():
    iw = _fully_enabled_instrument()
    iw._unit_forms["tubing_pre_column"].element("length").value = 0.33

    iw._sample_loop_checkbox.value = False  # unrelated change -> full _rebuild()

    assert iw.flow_sheet.tubing_pre_column.length == 0.33
    assert iw._unit_forms["tubing_pre_column"].element("length").value == 0.33


def test_unchecking_a_tubing_unit_removes_it_and_its_form():
    iw = _fully_enabled_instrument()

    iw._unit_checkboxes["tubing_pre_injection"].value = False

    assert "tubing_pre_injection" not in [u.name for u in iw.flow_sheet.units]
    assert iw._unit_form_boxes["tubing_pre_injection"].children == ()
    assert "tubing_pre_injection" not in iw._unit_forms


def test_unchecking_mixer_respects_lcflowsheets_own_forced_bypass_value():
    # LCFlowSheet never actually removes the mixer (always needed as the
    # buffer junction) -- it forces init_liquid_volume=1e-9 instead. Applying
    # a persisted/seed value on top of that would silently undo the bypass.
    iw = _fully_enabled_instrument()
    iw._unit_forms["mixer"].element("init_liquid_volume").value = 5e-5

    iw._unit_checkboxes["mixer"].value = False

    assert "mixer" in [u.name for u in iw.flow_sheet.units]  # never actually removed
    assert iw.flow_sheet.mixer.init_liquid_volume == 1e-9  # LCFlowSheet's own forced value
    assert iw._unit_form_boxes["mixer"].children == ()
    assert "mixer" not in iw._unit_forms

    iw._unit_checkboxes["mixer"].value = True
    assert iw.flow_sheet.mixer.init_liquid_volume == 5e-5  # the earlier edit, not the seed default


def test_default_instrument_builds_a_flow_sheet_with_only_the_column_ticked():
    iw = InstrumentWidget()

    assert iw.flow_sheet is not None
    assert iw._unit_checkboxes["column"].value is True
    assert all(cb.value is False for n, cb in iw._unit_checkboxes.items() if n != "column")
    assert set(iw.bypass_units()) == set(iw._unit_checkboxes) - {"column"}


def test_unit_values_round_trip_through_snapshot_and_apply_state():
    iw = _fully_enabled_instrument()
    iw._unit_forms["mixer"].element("init_liquid_volume").value = 2.5e-5
    iw._unit_forms["tubing_detectors"].element("axial_dispersion").value = 3e-8

    state = iw.snapshot()
    assert state.unit_values["mixer"]["init_liquid_volume"] == 2.5e-5
    assert state.unit_values["tubing_detectors"]["axial_dispersion"] == 3e-8
    # Plain scalars, not CADET-Process's internal list-wrapped storage shape.
    assert isinstance(state.unit_values["tubing_detectors"]["axial_dispersion"], float)

    iw2 = _fully_enabled_instrument()
    iw2.apply_state(state)

    assert iw2.flow_sheet.mixer.init_liquid_volume == 2.5e-5
    assert iw2._unit_forms["tubing_detectors"].element("axial_dispersion").value == 3e-8


@pytest.mark.parametrize("bad", [0.0, -1e-9, float("nan"), float("inf")])
def test_bad_sample_loop_volume_flags_the_field_and_withholds_the_flow_sheet(bad):
    iw = _instrument_with_loop()
    seen = []
    iw.add_listener(seen.append)

    iw._loop_volume_field.value = bad

    assert iw._loop_volume_field.error
    assert iw.flow_sheet is None
    assert seen[-1] is None
    assert "Sample loop volume" in iw.status.value


def test_sample_loop_volume_recovers_after_a_bad_value():
    iw = _instrument_with_loop()
    seen = []
    iw.add_listener(seen.append)
    iw._loop_volume_field.value = 0.0

    iw._loop_volume_field.value = 2e-7

    assert iw._loop_volume_field.error == ""
    assert iw.flow_sheet is not None
    assert seen[-1] is iw.flow_sheet
    assert "built" in iw.status.value


@pytest.mark.parametrize("bad", [0.0, -1e-3])
def test_bad_sample_loop_diameter_only_matters_when_not_auto_derived(bad):
    iw = _instrument_with_loop()
    iw._loop_diameter_field.value = bad
    assert iw._loop_diameter_field.error == ""
    assert iw.flow_sheet is not None

    iw._loop_diameter_auto_checkbox.value = False

    assert iw._loop_diameter_field.error
    assert iw.flow_sheet is None

    iw._loop_diameter_field.value = 1e-3

    assert iw._loop_diameter_field.error == ""
    assert iw.flow_sheet is not None


def test_bad_sample_loop_volume_is_ignored_while_the_loop_is_unchecked():
    iw = _instrument_with_loop()
    iw._loop_volume_field.value = 0.0
    assert iw.flow_sheet is None

    iw._sample_loop_checkbox.value = False

    assert iw._loop_volume_field.error == ""
    assert iw.flow_sheet is not None


@pytest.mark.parametrize(
    ("unit", "param", "bad"),
    [
        ("mixer", "init_liquid_volume", 0.0),
        ("mixer", "init_liquid_volume", -1.0),
        ("tubing_pre_injection", "length", 0.0),
        ("tubing_pre_injection", "diameter", -1e-3),
        ("tubing_detectors", "axial_dispersion", -1.0),
        ("tubing_pre_column", "length", float("nan")),
        ("tubing_post_column", "diameter", float("inf")),
    ],
)
def test_bad_unit_field_flags_the_field_and_withholds_the_flow_sheet_until_fixed(unit, param, bad):
    iw = _fully_enabled_instrument()
    seen = []
    iw.add_listener(seen.append)
    good = iw._unit_forms[unit].element(param).value

    iw._unit_forms[unit].element(param).value = bad

    assert iw._unit_forms[unit].element(param).error
    assert iw.flow_sheet is None
    assert seen == [None]
    assert "Invalid System inputs" in iw.status.value

    iw._unit_forms[unit].element(param).value = good

    assert iw._unit_forms[unit].element(param).error == ""
    assert iw.flow_sheet is not None
    assert seen[-1] is iw.flow_sheet
    assert len(seen) == 2


def test_zero_axial_dispersion_is_accepted():
    iw = _fully_enabled_instrument()

    iw._unit_forms["tubing_detectors"].element("axial_dispersion").value = 0.0

    assert iw._unit_forms["tubing_detectors"].element("axial_dispersion").error == ""
    assert iw.flow_sheet is not None


def test_set_required_units_locks_and_unlocks_the_sample_loop_standalone():
    iw = InstrumentWidget()
    assert iw._sample_loop_checkbox.value is False

    iw.set_required_units({"sample_loop"}, reason="Pulse Injection")

    assert iw._sample_loop_checkbox.value is True
    assert iw._sample_loop_checkbox.disabled is True
    assert "Pulse Injection needs a sample loop" in iw._loop_lock_note.value
    assert "sample_loop" in [u.name for u in iw.flow_sheet.units]

    iw.set_required_units(set())

    assert iw._sample_loop_checkbox.value is False
    assert iw._sample_loop_checkbox.disabled is False
    assert iw._loop_lock_note.layout.display == "none"


def test_set_required_units_does_not_rebuild_when_nothing_changes():
    iw = InstrumentWidget()
    iw.set_required_units({"sample_loop"})
    seen = []
    iw.add_listener(seen.append)

    iw.set_required_units({"sample_loop"})
    iw.set_required_units({"sample_loop"}, reason="Step Elution")

    assert seen == []


def test_set_required_units_rejects_unknown_units():
    with pytest.raises(ValueError):
        InstrumentWidget().set_required_units({"mixer"})
