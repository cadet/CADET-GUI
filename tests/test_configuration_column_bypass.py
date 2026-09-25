from __future__ import annotations

import warnings

from cadetgui.widgets.composite import (
    ConfigurationWidget,
    InstrumentWidget,
    WorkbenchWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


def _bound():
    instrument = InstrumentWidget()
    return ConfigurationWidget(instrument=instrument), instrument


def _column_off(instrument, off=True):
    instrument._unit_checkboxes["column"].value = not off


def _controls(cfg):
    return [
        cfg._column_picker,
        cfg._binding_picker,
        cfg._show_optional_column_checkbox,
        cfg._show_optional_binding_checkbox,
        *cfg._multiplex_checkboxes.values(),
        *cfg._column_form._elements.values(),
        *cfg._binding_form._elements.values(),
    ]


def _all_disabled(cfg):
    return all(c.disabled for c in _controls(cfg))


def _none_disabled(cfg):
    return not any(c.disabled for c in _controls(cfg))


def _notes_shown(cfg):
    return (
        cfg._column_bypass_note.layout.display != "none",
        cfg._binding_bypass_note.layout.display != "none",
    )


def test_enabled_by_default():
    cfg, _ = _bound()
    assert _none_disabled(cfg)
    assert _notes_shown(cfg) == (False, False)
    assert cfg._column_form.disabled is False
    assert cfg._binding_form.disabled is False


def test_bypassing_the_column_greys_out_column_and_binding_controls():
    cfg, instrument = _bound()
    _column_off(instrument)
    assert _all_disabled(cfg)
    assert cfg._column_form.disabled and cfg._binding_form.disabled
    assert cfg._column_form._btn_reset.disabled and cfg._binding_form._btn_reset.disabled
    assert _notes_shown(cfg) == (True, True)
    assert "bypassed" in cfg._column_bypass_note.value

    _column_off(instrument, off=False)
    assert _none_disabled(cfg)
    assert _notes_shown(cfg) == (False, False)
    assert not cfg._column_form._btn_reset.disabled


def test_values_survive_a_bypass_round_trip():
    cfg, instrument = _bound()
    cfg._column_form.set_values({"length": 0.123})
    binding_name = next(iter(cfg._binding_form.collect_values()))
    cfg._binding_form.set_values({binding_name: [7.5]})
    column_before = cfg._column_form.collect_values()
    binding_before = cfg._binding_form.collect_values()
    assert column_before["length"] == 0.123

    _column_off(instrument)
    assert cfg._column_form.collect_values() == column_before
    assert cfg._binding_form.collect_values() == binding_before
    snap = cfg._snapshot_state()
    assert snap.column_values == column_before
    assert snap.binding_values == binding_before

    _column_off(instrument, off=False)
    assert cfg._column_form.collect_values() == column_before
    assert cfg._binding_form.collect_values() == binding_before
    assert cfg.flow_sheet.column.length == 0.123
    assert _none_disabled(cfg)


def test_values_survive_an_unrelated_system_change():
    cfg, instrument = _bound()
    cfg._column_form.set_values({"length": 0.321})
    instrument._unit_checkboxes["mixer"].value = True
    assert cfg._column_form.collect_values()["length"] == 0.321
    assert cfg.flow_sheet.column.length == 0.321


def test_process_still_builds_while_the_column_is_bypassed():
    cfg, instrument = _bound()
    _column_off(instrument)
    assert instrument.flow_sheet is not None
    assert cfg.process is not None
    assert cfg._model_form.built is not None


def test_invalid_column_values_do_not_block_the_build_while_bypassed():
    cfg, instrument = _bound()
    _column_off(instrument)
    cfg._column_form.element("length").value = -1.0
    assert cfg._column_form.built is None
    assert cfg.process is not None
    assert instrument.flow_sheet is not None


def test_changing_a_disabled_flag_does_not_rebuild_the_forms():
    cfg, instrument = _bound()
    column_form, binding_form = cfg._column_form, cfg._binding_form
    cfg._column_form.set_disabled(True)
    cfg._column_form.set_disabled(False)
    assert cfg._column_form is column_form
    assert cfg._binding_form is binding_form


def test_loading_a_state_with_the_column_bypassed_comes_up_disabled():
    source, source_instrument = _bound()
    source._column_form.set_values({"length": 0.222})
    _column_off(source_instrument)
    state = source._snapshot_state()
    assert "column" in state.instrument.bypass_units

    target, target_instrument = _bound()
    assert _none_disabled(target)
    target._apply_state("loaded", state)
    assert "column" in target_instrument.bypass_units()
    assert _all_disabled(target)
    assert _notes_shown(target) == (True, True)
    assert target._column_form.collect_values()["length"] == 0.222
    assert target.process is not None

    _column_off(target_instrument, off=False)
    assert _none_disabled(target)
    assert target._column_form.collect_values()["length"] == 0.222
    assert target.flow_sheet.column.length == 0.222


def test_loading_a_column_state_re_enables_a_bypassed_widget():
    cfg, instrument = _bound()
    with_column = cfg._snapshot_state()
    _column_off(instrument)
    assert _all_disabled(cfg)
    cfg._apply_state("loaded", with_column)
    assert "column" not in instrument.bypass_units()
    assert _none_disabled(cfg)


def test_workbench_wiring():
    wb = WorkbenchWidget()
    wb.instrument._unit_checkboxes["column"].value = False
    assert wb.configuration._column_picker.disabled
    assert wb.configuration._binding_picker.disabled


def test_standalone_configuration_is_never_disabled():
    cfg = ConfigurationWidget()
    assert cfg._column_picker.disabled is False
    assert cfg._column_form.disabled is False
    assert _notes_shown(cfg) == (False, False)
