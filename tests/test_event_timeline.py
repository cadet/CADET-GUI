from __future__ import annotations

import warnings

import cadetgui.io.configuration_store as configuration_store
import pytest
from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES, PARAMS
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)

LWE = INSTRUMENT_TEMPLATES["Load–Wash–Elute (LWE)"]
ML_MIN_LABEL = r"Flow rate / \frac{\mathrm{mL}}{\mathrm{min}}"
DEFAULT_FLOW_ML_MIN = PARAMS["flow_rate_wash"].default / (1e-6 / 60.0)
WASH_MIN = PARAMS["delta_t_wash"].default / 60.0
ELUTE_MIN = PARAMS["delta_t_elute"].default / 60.0
FINAL_WASH_MIN = PARAMS["delta_t_final_wash"].default / 60.0
GRADIENT_END_MIN = WASH_MIN + ELUTE_MIN


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

    wash, gradient = WASH_MIN / 2, WASH_MIN + ELUTE_MIN / 2
    final_wash = GRADIENT_END_MIN + FINAL_WASH_MIN / 2
    assert _value_at(a, wash) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(b, wash) == pytest.approx(0.0, abs=1e-9)
    assert 0.0 < _value_at(a, gradient) < DEFAULT_FLOW_ML_MIN
    assert _value_at(a, gradient) + _value_at(b, gradient) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(a, final_wash) == pytest.approx(0.0, abs=1e-9)
    assert _value_at(b, final_wash) == pytest.approx(DEFAULT_FLOW_ML_MIN)


def test_lwe_phases_and_sample_injection_marker(lwe_widget):
    chart = lwe_widget._event_chart

    end = GRADIENT_END_MIN + FINAL_WASH_MIN
    assert chart.phases == [
        {"name": "Wash", "start": 0.0, "end": pytest.approx(WASH_MIN)},
        {"name": "Elute (gradient)", "start": pytest.approx(WASH_MIN),
         "end": pytest.approx(GRADIENT_END_MIN)},
        {"name": "Final wash", "start": pytest.approx(GRADIENT_END_MIN), "end": pytest.approx(end)},
    ]
    assert chart.markers == [{"name": "Sample injection", "time": 0.0}]
    assert chart.series[0]["times"][-1] == pytest.approx(end)


def test_changing_a_duration_moves_the_phase_boundaries(lwe_widget):
    chart = lwe_widget._event_chart

    wash = WASH_MIN / 2
    lwe_widget._model_form.element("delta_t_wash").value = wash * 60.0

    gradient_end = wash + ELUTE_MIN
    assert [(p["start"], p["end"]) for p in chart.phases] == pytest.approx(
        [(0.0, wash), (wash, gradient_end), (gradient_end, gradient_end + FINAL_WASH_MIN)]
    )
    a = _series(chart)["Buffer a"]
    assert _value_at(a, wash - 0.5) == pytest.approx(DEFAULT_FLOW_ML_MIN)
    assert _value_at(a, wash + 0.5) < DEFAULT_FLOW_ML_MIN


def test_changing_the_flow_rate_changes_the_step_heights(lwe_widget):
    lwe_widget._model_form.element("flow_rate_wash").value = 2 * PARAMS["flow_rate_wash"].default

    a = _series(lwe_widget._event_chart)["Buffer a"]
    assert _value_at(a, WASH_MIN / 2) == pytest.approx(2 * DEFAULT_FLOW_ML_MIN)


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
