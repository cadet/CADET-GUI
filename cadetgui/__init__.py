"""Widget-based GUI layer on top of CADET-Process.

`WorkbenchWidget` and `CharacterizationWorkbenchWidget` are the ready-made benches;
`ParametersWidget`, `FlowSheetWidget`, `EventsWidget` and `SimulationWidget` each show
one CADET-Process object. They load lazily, so `import cadetgui` stays cheap.
"""
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:
    from .widgets.composite import (
        CharacterizationWorkbenchWidget,
        EventsWidget,
        FlowSheetWidget,
        ParametersWidget,
        SimulationWidget,
        WorkbenchWidget,
    )

__all__ = [
    "WorkbenchWidget",
    "CharacterizationWorkbenchWidget",
    "ParametersWidget",
    "FlowSheetWidget",
    "EventsWidget",
    "SimulationWidget",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .widgets import composite

        return getattr(composite, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
