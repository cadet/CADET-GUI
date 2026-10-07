from __future__ import annotations

from typing import Any

import numpy as np
from CADETProcess.simulator import Cadet

_MAX_STEP = 1.0
_POINTS_PER_CYCLE = 5000
_POINTS_PER_SECTION = 20
_MAX_POINTS = 20000


def output_time_step(process: Any) -> float:
    """Return the output time step for `process`: finer for short cycles and sections."""
    sections = np.diff(process.section_times)
    step = min(
        _MAX_STEP,
        process.cycle_time / _POINTS_PER_CYCLE,
        sections[sections > 0].min() / _POINTS_PER_SECTION,
    )
    return max(step, process.cycle_time / _MAX_POINTS)


class Simulator(Cadet):
    """CADET simulator whose output grid follows `output_time_step` of each process."""

    def get_solution_time(self, process: Any, cycle: int = 1) -> np.ndarray:
        """Return the time vector for one cycle of `process` at its output time step."""
        self.time_resolution = output_time_step(process)
        return super().get_solution_time(process, cycle)


def run_process(process: Any, **kwargs: Any) -> Any:
    """Simulate `process` with CADET-Core and return the SimulationResults."""
    return Simulator().simulate(process, **kwargs)
