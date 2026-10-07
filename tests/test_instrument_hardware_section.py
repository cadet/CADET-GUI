from __future__ import annotations

import warnings

from cadetgui.widgets.composite import (
    CharacterizationWorkbenchWidget,
    InstrumentWidget,
    WorkbenchWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


def test_default_is_collapsed_with_summary():
    iw = InstrumentWidget()
    assert iw.hardware_expanded is False
    assert iw._hardware_body.layout.display == "none"
    assert iw._hardware_summary.value == "Column only"
    assert iw._hardware_toggle.icon == "chevron-right"


def test_toggle_button_and_setter_expand_and_collapse():
    iw = InstrumentWidget()
    iw._hardware_toggle.click()
    assert iw.hardware_expanded is True
    assert iw._hardware_body.layout.display == ""
    assert iw._hardware_toggle.icon == "chevron-down"
    iw._hardware_toggle.click()
    assert iw.hardware_expanded is False
    iw.set_hardware_expanded(True)
    assert iw.hardware_expanded is True
    iw.set_hardware_expanded(False)
    assert iw.hardware_expanded is False


def test_constructor_can_start_expanded():
    assert InstrumentWidget(hardware_expanded=True).hardware_expanded is True


def test_diagram_and_template_picker_stay_outside_the_section():
    iw = InstrumentWidget()
    assert iw._diagram.root not in iw._flow_path_section.children
    assert iw._template_picker not in iw._flow_path_section.children
    assert iw._diagram.root in iw.root.children
    assert iw._template_picker in iw.root.children


def test_enabling_units_while_collapsed_updates_summary_and_diagram():
    iw = InstrumentWidget()
    before = iw.bypass_units()
    diagram_before = iw._diagram.root.value
    iw._unit_checkboxes["mixer"].value = True
    iw._unit_checkboxes["tubing_detectors"].value = True
    assert iw._hardware_summary.value == "Column + mixer, tubing (detectors)"
    assert iw.hardware_expanded is False
    assert "mixer" not in iw.bypass_units()
    assert set(before) - set(iw.bypass_units()) == {"mixer", "tubing_detectors"}
    assert iw._diagram.root.value != diagram_before


def test_collapsing_does_not_change_bypass_units_or_snapshot():
    iw = InstrumentWidget(hardware_expanded=True)
    iw._unit_checkboxes["tubing_pre_column"].value = True
    bypass, snap = iw.bypass_units(), iw.snapshot()
    iw.set_hardware_expanded(False)
    assert iw.bypass_units() == bypass
    assert iw.snapshot() == snap


def test_summary_lists_multiple_tubing_segments_in_physical_order():
    iw = InstrumentWidget()
    iw._unit_checkboxes["tubing_detectors"].value = True
    iw._unit_checkboxes["tubing_pre_injection"].value = True
    assert iw._hardware_summary.value == "Column + tubing (pre-injection, detectors)"


def test_required_sample_loop_is_visible_in_collapsed_summary():
    iw = InstrumentWidget()
    iw.set_required_units(["sample_loop"], reason="Pulse Injection")
    assert iw.hardware_expanded is False
    assert iw._hardware_summary.value == "Column + sample loop (required by template)"
    iw.set_required_units([])
    assert iw._hardware_summary.value == "Column only"


def test_user_chosen_sample_loop_is_in_summary():
    iw = InstrumentWidget()
    iw._sample_loop_checkbox.value = True
    assert iw._hardware_summary.value == "Column + sample loop"


def _column_toggle_shown(iw):
    """Whether the column checkbox is reachable and not hidden inside the section."""
    checkbox = iw._unit_checkboxes["column"]

    def contains(box):
        return any(c is checkbox or contains(c) for c in getattr(box, "children", ()))

    return (
        contains(iw._hardware_body)
        and checkbox.layout.display != "none"
        and iw._unit_boxes["column"].layout.display != "none"
    )


def test_column_toggle_is_offered_in_a_standalone_instrument():
    assert _column_toggle_shown(InstrumentWidget()) is True


def test_bypassed_column_round_trips():
    source = InstrumentWidget()
    source._unit_checkboxes["column"].value = False
    state = source.snapshot()
    assert "column" in state.bypass_units

    target = InstrumentWidget()
    target.apply_state(state)
    assert "column" in target.bypass_units()
    assert target.snapshot() == state
    assert target._hardware_summary.value == "No column"
    assert _column_toggle_shown(target) is True
    assert target.hardware_expanded is True


def test_apply_state_expands_only_for_non_default_hardware():
    default = InstrumentWidget().snapshot()
    iw = InstrumentWidget()
    iw.apply_state(default)
    assert iw.hardware_expanded is False

    source = InstrumentWidget()
    source._unit_checkboxes["mixer"].value = True
    iw.apply_state(source.snapshot())
    assert iw.hardware_expanded is True
    assert iw._hardware_summary.value == "Column + mixer"


def test_workbench_builds_its_instrument_collapsed_with_column_toggle():
    wb = WorkbenchWidget()
    assert wb.instrument.hardware_expanded is False
    assert _column_toggle_shown(wb.instrument) is True


def test_characterization_workbench_builds_its_instrument_expanded_with_column_toggle():
    wb = CharacterizationWorkbenchWidget()
    assert wb.instrument.hardware_expanded is True
    assert _column_toggle_shown(wb.instrument) is True


def test_passed_in_instrument_is_left_alone():
    iw = InstrumentWidget()
    wb = WorkbenchWidget(instrument=iw)
    assert wb.instrument is iw
    assert iw.hardware_expanded is False

    iw2 = InstrumentWidget(hardware_expanded=True)
    cw = CharacterizationWorkbenchWidget(instrument=iw2)
    assert cw.instrument is iw2
