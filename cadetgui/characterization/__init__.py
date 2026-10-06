"""Characterization core: studies, measurements, parameter stores and step fits.

Names below load lazily from their modules, so importing one module of this
package does not import the others.
"""
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .comparison import Comparison
    from .parameter_store import ParameterStore
    from .runner import StepResult, StepSetup
    from .step_checks import StepStatus, study_steps_status
    from .study import Study

_EXPORTS = {
    "Study": "study",
    "Comparison": "comparison",
    "ParameterStore": "parameter_store",
    "StepSetup": "runner",
    "StepResult": "runner",
    "StepStatus": "step_checks",
    "study_steps_status": "step_checks",
}

__all__ = [
    "Study",
    "Comparison",
    "ParameterStore",
    "StepSetup",
    "StepResult",
    "StepStatus",
    "study_steps_status",
]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
