from __future__ import annotations

import warnings
from dataclasses import replace

import numpy as np
import pytest
from cadetgui import process_builder
from cadetgui.cadetprocessadapter import BINDING_MODELS, INSTRUMENT_TEMPLATES
from cadetgui.process_builder import build_process, check_recipe
from cadetgui.simulation import run_process
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget
from CADETProcess.simulator import Cadet

warnings.filterwarnings("ignore", category=UserWarning)


def _configs_equal(a, b) -> bool:
    """Recursively compare two `Cadet().get_process_config()` trees, array-safe."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_configs_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple, np.ndarray)) or isinstance(b, (list, tuple, np.ndarray)):
        return np.array_equal(np.asarray(a), np.asarray(b))
    return a == b


def _config(process):
    return Cadet().get_process_config(process)


def _bound(
    instrument: InstrumentWidget | None = None,
) -> tuple[ConfigurationWidget, InstrumentWidget]:
    instrument = instrument or InstrumentWidget()
    return ConfigurationWidget(instrument=instrument), instrument


def _assert_equivalent(cw: ConfigurationWidget) -> None:
    """Snapshot `cw`, rebuild headlessly, and assert the CADET-Core configs match."""
    state = cw.snapshot()
    rebuilt = build_process(state)
    assert _configs_equal(_config(cw.process), _config(rebuilt))


def test_build_process_matches_the_default_pulse_injection_configuration():
    cw, _ = _bound()
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    _assert_equivalent(cw)


def test_build_process_matches_a_configuration_with_bypassed_tubing():
    cw, instrument = _bound()
    instrument._unit_checkboxes["tubing_pre_column"].value = False
    instrument._unit_checkboxes["tubing_detectors"].value = False
    _assert_equivalent(cw)


def test_build_process_matches_a_configuration_with_the_sample_loop_included():
    cw, instrument = _bound()
    instrument._sample_loop_checkbox.value = True
    instrument._loop_diameter_auto_checkbox.value = False
    instrument._loop_diameter_field.value = 1e-3
    instrument._loop_volume_field.value = 80e-9
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    _assert_equivalent(cw)


def test_build_process_matches_an_sma_binding_configuration_with_multiple_components():
    cw, _ = _bound()
    cw.components = ["Salt", "Protein", "Impurity"]
    cw._binding_picker.value = BINDING_MODELS["Steric Mass Action (SMA)"]
    _assert_equivalent(cw)


def test_build_process_matches_a_configuration_with_the_column_bypassed():
    cw, instrument = _bound()
    instrument._unit_checkboxes["column"].value = False
    _assert_equivalent(cw)


def test_build_process_matches_a_standalone_configuration():
    cw = ConfigurationWidget()
    _assert_equivalent(cw)


def test_build_process_overrides_replace_model_values_without_touching_the_saved_state():
    cw, _ = _bound()
    state = cw.snapshot()

    baseline = build_process(state)
    overridden = build_process(state, overrides={"flow_rate": 5e-6})

    flow_rate_event = next(e for e in overridden.events if e.name == "phase_0_F")
    assert flow_rate_event.state == 5e-6
    assert not _configs_equal(_config(baseline), _config(overridden))
    assert state.model_values.get("flow_rate") != 5e-6


def test_build_process_raises_for_an_unregistered_column_key():
    cw, _ = _bound()
    state = replace(cw.snapshot(), column_key="Not a real column")
    with pytest.raises(ValueError, match="column"):
        build_process(state)


def test_build_process_raises_for_an_unregistered_template_key():
    cw, _ = _bound()
    state = replace(cw.snapshot(), template_key="Not a real template")
    with pytest.raises(ValueError, match="template"):
        build_process(state)


def test_build_process_simulates_to_the_same_outlet_as_the_widget():
    cw, _ = _bound()
    state = cw.snapshot()
    rebuilt = build_process(state)

    result_widget = run_process(cw.process)
    result_rebuilt = run_process(rebuilt)

    assert np.allclose(
        result_widget.solution["outlet"]["outlet"].solution,
        result_rebuilt.solution["outlet"]["outlet"].solution,
    )


def test_check_recipe_builds_once_per_content_and_reports_errors(monkeypatch):
    cw, _ = _bound()
    state = cw.snapshot()
    process_builder.clear_recipe_checks()
    calls = []
    original = process_builder.build_process

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(process_builder, "build_process", counting)

    check = check_recipe(state)
    assert check_recipe(replace(state)) is check
    assert len(calls) == 1
    assert check.error is None
    assert "column" in check.units
    assert check.species == tuple(state.components)
    assert check.signal_options
    assert check.has_parameter("flow_sheet.column.length")
    assert not check.has_parameter("flow_sheet.column.not_a_parameter")

    check_recipe(state, {"flow_rate": 5e-6})
    assert len(calls) == 2

    broken = check_recipe(replace(state, column_key="Not a real column"))
    assert broken.error and "column" in broken.error
    assert broken.units == () and not broken.has_parameter("flow_sheet.column.length")
