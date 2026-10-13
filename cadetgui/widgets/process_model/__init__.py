"""One widget per `CADETProcess.processModel` object, for learning the concepts."""

from .component_system import ComponentSystemWidget
from .events import EventEditor
from .flow_sheet import FlowSheetWidget
from .process import ProcessWidget
from .profiles import PolynomialEditor
from .simulation import SimulationWidget
from .unit_operations import (
    UnitOperationsWidget,
    UnitOperationWidget,
    UnitParametersEditor,
)

__all__ = [
    "ComponentSystemWidget",
    "UnitOperationsWidget",
    "UnitOperationWidget",
    "UnitParametersEditor",
    "FlowSheetWidget",
    "ProcessWidget",
    "EventEditor",
    "PolynomialEditor",
    "SimulationWidget",
]
