"""Chart series from solutions and measured data."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from cadetgui.widgets.ui.plotting import (
    decimate_minmax,
    reference_series,
    solution_series,
)


def solution(values, names):
    values = np.asarray(values, dtype=float)
    return SimpleNamespace(
        solution=values, time=np.arange(len(values)) * 60.0,
        component_system=SimpleNamespace(names=names),
    )


def test_decimation_keeps_short_traces_and_the_ends_and_peak_of_long_ones():
    short = np.arange(10.0)
    kept = decimate_minmax(short, 2 * short, max_points=100)
    assert kept == (short.tolist(), (2 * short).tolist())

    t = np.linspace(0, 100, 50_001)
    v = np.zeros_like(t)
    v[31_337] = 9.0

    times, values = decimate_minmax(t, v, max_points=1000)

    assert len(times) < 1500 and times == sorted(times)
    assert (times[0], times[-1], max(values)) == (0.0, 100.0, 9.0)


def test_solution_series_is_one_series_per_component_in_minutes():
    series = solution_series(solution([[1, 10], [2, 20], [3, 30]], ["Salt", "Protein"]))

    assert [s["name"] for s in series] == ["Salt", "Protein"]
    assert series[0]["times"] == [0.0, 1.0, 2.0]
    assert series[1]["values"] == [10.0, 20.0, 30.0]


def test_solution_series_is_none_unless_time_by_component():
    assert solution_series(solution(np.zeros((3, 5, 2)), ["A", "B"])) is None
    assert solution_series(solution(np.zeros((3, 3)), ["A", "B"])) is None


def test_reference_series_is_a_dashed_reference_in_minutes():
    assert reference_series("measured", [0, 60, 120], [1, 2, 3]) == {
        "name": "measured", "times": [0.0, 1.0, 2.0], "values": [1.0, 2.0, 3.0],
        "dashed": True, "reference": True,
    }
