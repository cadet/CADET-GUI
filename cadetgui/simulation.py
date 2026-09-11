from __future__ import annotations

from typing import Any

try:
    from CADETProcess.simulator import Cadet
except Exception:
    Cadet = None  # type: ignore


def run_process(process: Any, **kwargs: Any) -> Any:
    """
    Run a CADET-Process Process with the CADETProcess simulator.

    The simulator does not need the component system explicitly.
    """
    if Cadet is None:
        raise RuntimeError("CADETProcess.simulator is not available")
    sim = Cadet()
    return sim.simulate(process, **kwargs)
