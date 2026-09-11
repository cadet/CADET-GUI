from __future__ import annotations

import warnings

from cadetgui.widgets.composite import WorkbenchWidget

warnings.filterwarnings("ignore", category=UserWarning)


def test_workbench_builds_and_wires_the_three_widgets():
    wb = WorkbenchWidget()

    assert wb.configuration.process is not None  # auto-committed on construction
    assert wb.solution.process is wb.configuration.process  # bind_to_config picked it up


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
