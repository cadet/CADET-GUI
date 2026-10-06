"""File I/O: measured data, saved configurations and simulation runs.

Names below load lazily from their modules, so importing one module of this
package does not import the others.
"""
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .configuration_store import ConfigurationState, InstrumentState
    from .experimental_data import (
        ExperimentalRun,
        read_experimental_csv,
        write_experimental_csv,
    )
    from .run_store import RunRecordState

_EXPORTS = {
    "ConfigurationState": "configuration_store",
    "InstrumentState": "configuration_store",
    "ExperimentalRun": "experimental_data",
    "read_experimental_csv": "experimental_data",
    "write_experimental_csv": "experimental_data",
    "RunRecordState": "run_store",
}

__all__ = [
    "ConfigurationState",
    "InstrumentState",
    "ExperimentalRun",
    "read_experimental_csv",
    "write_experimental_csv",
    "RunRecordState",
]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
