"""Ready-made benches and the frame they share."""

from .characterization import CharacterizationWorkbenchWidget
from .frame import BackendVersionsWidget, WorkspaceHeader, bench_root
from .instrument import InstrumentWorkbenchWidget

__all__ = [
    "InstrumentWorkbenchWidget",
    "CharacterizationWorkbenchWidget",
    "BackendVersionsWidget",
    "WorkspaceHeader",
    "bench_root",
]
