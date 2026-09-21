"""Task widgets assembled from elements + forms."""
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget, ExperimentalDataset
from .parameter_estimation import ParameterEstimationWidget
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
    "ParameterEstimationWidget",
    "WorkbenchWidget",
]
