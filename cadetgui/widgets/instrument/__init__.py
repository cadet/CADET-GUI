"""Widgets for an LC system and its template processes (`CADETProcess.instruments`)."""

from .configuration import ConfigurationWidget, FlowRateSection
from .data_import import DataImportWidget
from .instrument import InstrumentWidget
from .persistence import ConfigurationPersistence
from .run_history import RunHistoryWidget, RunRecord
from .solution import SolutionWidget
from .templates import TemplateEditor

__all__ = [
    "InstrumentWidget",
    "ConfigurationWidget",
    "FlowRateSection",
    "ConfigurationPersistence",
    "TemplateEditor",
    "SolutionWidget",
    "RunHistoryWidget",
    "RunRecord",
    "DataImportWidget",
]
