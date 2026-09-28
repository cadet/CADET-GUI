from __future__ import annotations

import warnings

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)

LWE = INSTRUMENT_TEMPLATES["Load–Wash–Elute (LWE)"]
ML_MIN_LABEL = r"Flow rate / \frac{\mathrm{mL}}{\mathrm{min}}"
DEFAULT_FLOW_ML_MIN = 60.0  # 1e-6 m^3/s


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


@pytest.fixture
def lwe_widget():
    cw = ConfigurationWidget(instrument=InstrumentWidget())
    cw._model_picker.value = LWE
    return cw


def _series(chart):
    return {s["name"]: s for s in chart.series}


def _value_at(series, t_min):
    times = series["times"]
    i = min(range(len(times)), key=lambda k: abs(times[k] - t_min))
    return series["values"][i]


def test_lwe_chart_excludes_valve_states_and_plots_only_buffer_flow_rates(lwe_widget):
    chart = lwe_widget._event_chart

    assert set(_series(chart)) == {"Buffer a", "Buffer b"}
    assert chart.y_label == ML_MIN_LABEL


def test_lwe_flow_rates_step_and_ramp_between_phases_in_ml_per_min(lwe_widget):
    series = _series(lwe_widget._event_chart)
    a, b = series["Buffer a"], series["Buffer b"]

    assert _value_at(a, 5.0) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(b, 5.0) == pytest.approx(0.0, abs=1e-9)
    assert 0.0 < _value_at(a, 20.0) < DEFAULT_FLOW_ML_MIN
    assert _value_at(a, 20.0) + _value_at(b, 20.0) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(a, 35.0) == pytest.approx(0.0, abs=1e-9)
    assert _value_at(b, 35.0) == pytest.approx(DEFAULT_FLOW_ML_MIN)


def test_lwe_phases_and_sample_injection_marker(lwe_widget):
    chart = lwe_widget._event_chart

    assert chart.phases == [
        {"name": "Wash", "start": 0.0, "end": 10.0},
        {"name": "Elute (gradient)", "start": 10.0, "end": 30.0},
        {"name": "Final wash", "start": 30.0, "end": 40.0},
    ]
    assert chart.markers == [{"name": "Sample injection", "time": 0.0}]
    assert chart.series[0]["times"][-1] == pytest.approx(40.0)


def test_changing_a_duration_moves_the_phase_boundaries(lwe_widget):
    chart = lwe_widget._event_chart

    lwe_widget._model_form.element("delta_t_wash").value = 300.0

    assert [(p["start"], p["end"]) for p in chart.phases] == [(0.0, 5.0), (5.0, 25.0), (25.0, 35.0)]
    a = _series(chart)["Buffer a"]
    assert _value_at(a, 4.0) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(a, 6.0) < DEFAULT_FLOW_ML_MIN


def test_changing_the_flow_rate_changes_the_step_heights(lwe_widget):
    lwe_widget._model_form.element("flow_rate_wash").value = 2.0e-6

    a = _series(lwe_widget._event_chart)["Buffer a"]
    assert _value_at(a, 5.0) == pytest.approx(2 * DEFAULT_FLOW_ML_MIN)


@pytest.mark.parametrize(
    ("template", "phase_names", "injects", "series_names"),
    [
        ("Breakthrough", ["Breakthrough"], False, {"Feed inlet"}),
        ("Step", ["Step"], False, {"Buffer b"}),
        ("Pulse Injection", ["Pulse injection"], True, {"Buffer a"}),
        ("Load–Wash–Elute (LWE)", ["Wash", "Elute (gradient)", "Final wash"], True, None),
        ("Step Elution", ["Wash", "Elute", "Final wash"], True, None),
    ],
)
def test_every_instrument_template_feeds_series_phases_and_markers(
    template, phase_names, injects, series_names
):
    cw = ConfigurationWidget(instrument=InstrumentWidget())
    cw._model_picker.value = INSTRUMENT_TEMPLATES[template]
    chart = cw._event_chart

    assert chart.y_label == ML_MIN_LABEL
    assert chart.series
    if series_names is not None:
        assert set(_series(chart)) == series_names
    for s in chart.series:
        assert len(s["times"]) == len(s["values"])
        assert all(v >= 0.0 for v in s["values"])
        assert max(s["values"]) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert [p["name"] for p in chart.phases] == phase_names
    assert chart.phases[0]["start"] == 0.0
    assert chart.phases[-1]["end"] == pytest.approx(cw.process.cycle_time / 60.0)
    assert bool(chart.markers) is injects


def test_standalone_template_keeps_concentration_series_without_phases():
    cw = ConfigurationWidget()
    chart = cw._event_chart

    assert chart.series
    assert chart.y_label.startswith("Concentration")
    assert chart.phases == []
    assert chart.markers == []
    assert max(chart.series[0]["values"]) == pytest.approx(10.0)
