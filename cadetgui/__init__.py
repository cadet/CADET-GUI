"""Widget-based GUI layer on top of CADET-Process.

`InstrumentWorkbenchWidget` and `CharacterizationWorkbenchWidget` are the ready-made
benches; `ComponentSystemWidget`, `UnitOperationsWidget`, `FlowSheetWidget`,
`ProcessWidget` and `SimulationWidget` each build or show one level of a CADET-Process
model. They load lazily, so `import cadetgui` stays cheap.

Packages mirror CADET-Process: `process_model`, `instrument`, `estimation` and
`characterization` hold the code without widgets, `widgets.<same name>` their widgets.
"""
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

if TYPE_CHECKING:
    from .widgets.benches.characterization import CharacterizationWorkbenchWidget
    from .widgets.benches.instrument import InstrumentWorkbenchWidget
    from .widgets.process_model.component_system import ComponentSystemWidget
    from .widgets.process_model.flow_sheet import FlowSheetWidget
    from .widgets.process_model.process import ProcessWidget
    from .widgets.process_model.simulation import SimulationWidget
    from .widgets.process_model.unit_operations import UnitOperationsWidget

__all__ = [
    "InstrumentWorkbenchWidget",
    "CharacterizationWorkbenchWidget",
    "ComponentSystemWidget",
    "UnitOperationsWidget",
    "FlowSheetWidget",
    "ProcessWidget",
    "SimulationWidget",
]


_BENCHES = ("InstrumentWorkbenchWidget", "CharacterizationWorkbenchWidget")


def __getattr__(name: str) -> Any:
    if name in __all__:
        from importlib import import_module

        package = "benches" if name in _BENCHES else "process_model"
        return getattr(import_module(f".widgets.{package}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
