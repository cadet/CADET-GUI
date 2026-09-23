from __future__ import annotations

import warnings

from cadetgui.widgets.composite import InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)


def _fully_enabled_instrument() -> InstrumentWidget:
    """An InstrumentWidget with "Use LC system" on and every unit checked.

    Both default to a leaner starting point now ("Use LC system" off; once
    on, only "column" is checked) -- most of this module is actually about
    the per-unit forms/bypass behavior once everything is in the flow path,
    so this restores that fuller state instead of every test doing so itself.
    """
    iw = InstrumentWidget()
    iw._use_lc_system_checkbox.value = True
    for checkbox in iw._unit_checkboxes.values():
        checkbox.value = True
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


def test_disabling_use_lc_system_clears_every_unit_form():
    iw = _fully_enabled_instrument()
    assert iw._unit_forms

    iw._use_lc_system_checkbox.value = False

    assert iw._unit_forms == {}
    assert all(box.children == () for box in iw._unit_form_boxes.values())


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
