from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from cadetgui.widgets._series import decimate_minmax, solution_series


def test_decimate_keeps_short_traces_untouched():
    t = np.arange(10.0)
    times, values = decimate_minmax(t, t * 2, max_points=100)

    assert times == t.tolist()
    assert values == (t * 2).tolist()


def test_decimate_thins_long_traces_but_keeps_endpoints_and_the_peak():
    t = np.linspace(0, 100, 50_001)
    v = np.zeros_like(t)
    v[31_337] = 9.0

    times, values = decimate_minmax(t, v, max_points=1000)

    assert len(times) < 1500
    assert times[0] == t[0] and times[-1] == t[-1]
    assert max(values) == 9.0
    assert times == sorted(times)


def _solution(values, names, time_s=None):
    values = np.asarray(values, dtype=float)
    time = np.arange(len(values), dtype=float) * 60 if time_s is None else time_s
    return SimpleNamespace(
        solution=values, time=time, component_system=SimpleNamespace(names=names)
    )


def test_solution_series_makes_one_series_per_component_in_minutes():
    sol = _solution([[1, 10], [2, 20], [3, 30]], ["Salt", "Protein"])

    series = solution_series(sol)

    assert [s["name"] for s in series] == ["Salt", "Protein"]
    assert series[0]["times"] == [0.0, 1.0, 2.0]
    assert series[1]["values"] == [10.0, 20.0, 30.0]


def test_solution_series_is_none_for_anything_but_a_time_by_component_trace():
    axial = _solution(np.zeros((3, 5, 2)), ["A", "B"])
    mismatched = _solution(np.zeros((3, 3)), ["A", "B"])

    assert solution_series(axial) is None
    assert solution_series(mismatched) is None
