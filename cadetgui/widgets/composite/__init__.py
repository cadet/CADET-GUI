# =========================================
# File: cadetgui/widgets/composite/__init__.py
# =========================================
"""Task widgets assembled from elements + forms.

See ai-docs/ARCHITECTURE.md's "Composition, not inheritance-of-everything" note.
"""
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget, ExperimentalDataset
from .run_history import RunHistoryWidget, RunRecord
from .solution import SolutionWidget
from .workbench import WorkbenchWidget

__all__ = [
    "ConfigurationWidget",
    "SolutionWidget",
    "RunHistoryWidget",
    "RunRecord",
    "DataImportWidget",
    "ExperimentalDataset",
    "WorkbenchWidget",
]
