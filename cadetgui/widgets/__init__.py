"""Composable widgets for CADET-GUI.

This subpackage provides:
- elements: atomic anywidget input controls
- forms: FormRenderer, rendering a ModelSpec into elements
- composite: task widgets assembled from elements + forms (Configuration,
  Solution, RunHistory, DataImport)

Public API re-exports the composite widgets, the most common entry point.
Import from `cadetgui.widgets.elements`/`.forms` directly for the lower layers.
"""
from .composite import (
    ConfigurationWidget,
    DataImportWidget,
    ExperimentalDataset,
    RunHistoryWidget,
    RunRecord,
    SolutionWidget,
)

__all__ = [
    "ConfigurationWidget",
    "SolutionWidget",
    "RunHistoryWidget",
    "RunRecord",
    "DataImportWidget",
    "ExperimentalDataset",
]
