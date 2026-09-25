"""Task widgets assembled from elements + forms."""
from .backend_versions import BackendVersionsWidget
from .characterization import CharacterizationWidget
from .characterization_workbench import CharacterizationWorkbenchWidget
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget, ExperimentalDataset
from .instrument import InstrumentWidget
from .parameter_estimation import ParameterEstimationWidget
from .parameter_history import ParameterHistoryWidget, ParameterPushRecord
from .run_history import RunHistoryWidget, RunRecord
from .solution import SolutionWidget
from .workbench import WorkbenchWidget
from .workspace_header import WorkspaceHeader

__all__ = [
    "BackendVersionsWidget",
    "InstrumentWidget",
    "ConfigurationWidget",
    "SolutionWidget",
    "RunHistoryWidget",
    "RunRecord",
    "DataImportWidget",
    "ExperimentalDataset",
    "ParameterEstimationWidget",
    "CharacterizationWidget",
    "CharacterizationWorkbenchWidget",
    "ParameterHistoryWidget",
    "ParameterPushRecord",
    "WorkbenchWidget",
    "WorkspaceHeader",
]
