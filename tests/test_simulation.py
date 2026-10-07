from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.simulation import Simulator, output_time_step


def _process(*section_times: float) -> SimpleNamespace:
    return SimpleNamespace(section_times=list(section_times), cycle_time=section_times[-1])


@pytest.mark.parametrize(
    "process, step",
    [
        (_process(0.0, 600.0), 0.12),
        (_process(0.0, 2.0, 600.0), 0.1),
        (_process(0.0, 0.01, 600.0), 0.03),
        (_process(0.0, 20000.0), 1.0),
    ],
)
def test_output_time_step_follows_cycle_and_shortest_section(process, step):
    assert output_time_step(process) == pytest.approx(step)


def test_simulator_output_grid_resolves_a_short_lab_scale_run():
    time = Simulator().get_solution_time(_process(0.0, 600.0))
    assert len(time) == 5001
    assert np.diff(time).max() == pytest.approx(0.12)
