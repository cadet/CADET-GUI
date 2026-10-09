"""Widget-based GUI layer on top of CADET-Process.

`WorkbenchWidget` and `CharacterizationWorkbenchWidget` are the ready-made benches;
`ComponentSystemWidget`, `UnitOperationsWidget`, `FlowSheetWidget`, `ProcessWidget` and
`SimulationWidget` each build or show one level of a CADET-Process model. They load
lazily, so `import cadetgui` stays cheap.
"""
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:
    from .widgets.composite import (
        CharacterizationWorkbenchWidget,
        ComponentSystemWidget,
        FlowSheetWidget,
        ProcessWidget,
        SimulationWidget,
        UnitOperationsWidget,
        WorkbenchWidget,
    )

__all__ = [
    "WorkbenchWidget",
    "CharacterizationWorkbenchWidget",
    "ComponentSystemWidget",
    "UnitOperationsWidget",
    "FlowSheetWidget",
    "ProcessWidget",
    "SimulationWidget",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .widgets import composite

        return getattr(composite, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
