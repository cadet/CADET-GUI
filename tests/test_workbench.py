from __future__ import annotations

import warnings

import cadetgui.configuration_store as configuration_store
import pytest
from cadetgui.widgets.composite import WorkbenchWidget

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def test_workbench_builds_and_wires_the_three_widgets():
    wb = WorkbenchWidget()

    assert wb.configuration.process is not None  # auto-committed on construction
    assert wb.solution.process is wb.configuration.process  # bind_to_config picked it up


def test_workbench_wires_parameter_estimation_to_configuration():
    wb = WorkbenchWidget()

    assert wb.parameter_estimation.param_space._param_add_picker.option_labels  # populated on bind
    assert wb.parameter_estimation._signal_picker.option_labels == []  # nothing previewed yet

    wb.parameter_estimation._on_preview(None)

    assert wb.parameter_estimation._signal_picker.option_labels
    assert wb.solution.result is None  # the Simulation tab's own run state is untouched


def test_workbench_shows_only_the_configuration_pane_initially():
    wb = WorkbenchWidget()

    assert wb.configuration.root.layout.display == ""
    assert wb.solution.root.layout.display == "none"
    assert wb.parameter_estimation.root.layout.display == "none"
    assert wb._nav.index == 0


def test_workbench_nav_switches_the_visible_pane():
    wb = WorkbenchWidget()

    wb._nav.index = 1  # Simulation

    assert wb.configuration.root.layout.display == "none"
    assert wb.solution.root.layout.display == ""
    assert wb.parameter_estimation.root.layout.display == "none"


def test_workbench_config_edits_still_flow_through_to_solution():
    wb = WorkbenchWidget()
    first_process = wb.solution.process

    wb.configuration._model_form.element("flow_rate").value = 3e-6

    assert wb.solution.process is wb.configuration.process
    assert wb.solution.process is not first_process


def test_workbench_accepts_prebuilt_widgets():
    from cadetgui.widgets.composite import (
        ConfigurationWidget,
        ParameterEstimationWidget,
        SolutionWidget,
    )

    cw = ConfigurationWidget()
    sw = SolutionWidget()
    pw = ParameterEstimationWidget()

    wb = WorkbenchWidget(configuration=cw, solution=sw, parameter_estimation=pw)

    assert wb.configuration is cw
    assert wb.solution is sw
    assert wb.parameter_estimation is pw
    assert sw.process is cw.process


def test_workbench_include_builds_only_the_requested_steps():
    wb = WorkbenchWidget(include=("Configuration", "Simulation"))

    assert wb.configuration is not None
    assert wb.solution is not None
    assert wb.parameter_estimation is None
    assert list(wb._nav.options) == ["Configuration", "Simulation"]
    assert wb.solution.process is wb.configuration.process


def test_workbench_include_rejects_unknown_step():
    with pytest.raises(ValueError):
        WorkbenchWidget(include=("Configuration", "Not A Step"))


def test_workbench_include_rejects_widget_for_excluded_step():
    from cadetgui.widgets.composite import ParameterEstimationWidget

    with pytest.raises(ValueError):
        WorkbenchWidget(
            include=("Configuration",), parameter_estimation=ParameterEstimationWidget()
        )
