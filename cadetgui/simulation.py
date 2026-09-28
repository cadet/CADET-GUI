from __future__ import annotations

from typing import Any

from CADETProcess.simulator import Cadet


def run_process(process: Any, **kwargs: Any) -> Any:
    """Simulate `process` with CADET-Core and return the SimulationResults."""
    return Cadet().simulate(process, **kwargs)
