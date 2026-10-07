from __future__ import annotations

import warnings

import cadetgui.configuration_store as configuration_store
import numpy as np
import pytest
from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES
from cadetgui.characterization_guide import EXPERIMENT_TYPES, with_implied_values
from cadetgui.parameter_store import ParameterStore, apply_store
from cadetgui.process_builder import build_process
from cadetgui.simulation import run_process
from cadetgui.widgets.composite import (
    CharacterizationWorkbenchWidget,
    ConfigurationWidget,
    InstrumentWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def _rise_and_end(result, unit, port):
    """Return `(max change, time of 99 % of it, end/max)` of the last component's signal."""
    solution = result.solution[unit][port]
    signal = np.asarray(solution.solution).reshape(len(solution.time), -1)[:, -1]
    change = signal - signal[0]
    peak = change.max()
    t_99 = float(np.asarray(solution.time)[np.argmax(change >= 0.99 * peak)])
    return peak, t_99, change[-1] / peak


def _assert_signal_inside_the_cycle(process, unit, port, label):
    peak, t_99, end = _rise_and_end(run_process(process), unit, port)
    assert peak > 1e-2, label
    assert t_99 < 0.9 * process.cycle_time, label
    assert end < 0.05 or end > 0.95, label


@pytest.mark.slow
@pytest.mark.parametrize("template", list(INSTRUMENT_TEMPLATES))
def test_default_template_signal_peaks_or_breaks_through_inside_the_cycle(template):
    cw = ConfigurationWidget(instrument=InstrumentWidget())
    cw.select_models(template=template)
    _assert_signal_inside_the_cycle(cw.process, "outlet", "inlet", template)


@pytest.mark.slow
@pytest.mark.parametrize("type_id", list(EXPERIMENT_TYPES))
def test_experiment_type_signal_peaks_or_breaks_through_inside_the_cycle(type_id):
    experiment = EXPERIMENT_TYPES[type_id]
    base = CharacterizationWorkbenchWidget().configuration.snapshot()
    process = build_process(experiment.apply(base, component="Probe"))
    apply_store(process, with_implied_values(ParameterStore(), experiment, "Probe"))
    unit, port = experiment.solution_path.split(".")[:2]
    _assert_signal_inside_the_cycle(process, unit, port, type_id)
