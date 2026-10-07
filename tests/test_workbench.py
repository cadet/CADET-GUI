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


def test_workbench_builds_and_wires_the_four_widgets():
    wb = WorkbenchWidget()

    assert wb.instrument.flow_sheet is not None
    assert wb.configuration.process is not None  # auto-committed
    assert wb.solution.process is wb.configuration.process  # bind_to_config picked it up


def test_workbench_wires_parameter_estimation_to_configuration():
    wb = WorkbenchWidget()

    assert wb.parameter_estimation.param_space._param_add_picker.option_labels  # populated on bind
    assert wb.parameter_estimation._signal_picker.option_labels  # populated on bind
    assert wb.parameter_estimation._display_result is None  # no preview until the pane opens
    wb._shell.show("Parameter Estimation")
    assert wb.parameter_estimation._display_result is not None
    assert wb.solution.result is None  # the Simulation tab's own run state is untouched


def test_estimation_preview_waits_for_its_pane_after_a_configuration_change():
    wb = WorkbenchWidget()
    wb._shell.show("Parameter Estimation")
    before = wb.parameter_estimation._display_result

    wb.configuration._model_form.element("flow_rate").value = 2e-6

    assert wb.parameter_estimation._display_result is before
    assert "updates when this pane is opened" in wb.parameter_estimation._preview_status.value
    wb._shell.show("Parameter Estimation")
    assert wb.parameter_estimation._display_result is not before


def test_workbench_shows_only_the_system_pane_initially():
    wb = WorkbenchWidget()

    assert wb.instrument.root.layout.display == ""
    assert wb.configuration.root.layout.display == "none"
    assert wb.solution.root.layout.display == "none"
    assert wb.parameter_estimation.root.layout.display == "none"
    assert wb._shell.nav.value == "System: Instrument"


def _keys(wb):
    return [o[1] if isinstance(o, tuple) else o for o in wb._shell.nav.options]


def test_workbench_nav_switches_the_visible_pane():
    wb = WorkbenchWidget()

    wb._shell.nav.index = _keys(wb).index("Simulation")

    assert wb.instrument.root.layout.display == "none"
    assert wb.configuration.root.layout.display == "none"
    assert wb.solution.root.layout.display == ""
    assert wb.parameter_estimation.root.layout.display == "none"


def test_workbench_component_edits_flow_through_to_solution():
    wb = WorkbenchWidget()
    first_process = wb.solution.process

    wb.configuration.components = ["Salt", "Protein"]

    assert wb.solution.process is wb.configuration.process
    assert wb.solution.process is not first_process


def test_workbench_config_edits_flow_through_to_solution():
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
    assert cw.process is not None  # bound to WorkbenchWidget's own default Instrument
    assert sw.process is cw.process


def test_workbench_sidebar_nests_instrument_and_process_under_system():
    wb = WorkbenchWidget()

    assert list(wb._shell.panes) == [
        "System: Instrument", "System: Process configuration", "Simulation",
        "Parameter Estimation",
    ]
    assert wb._shell._groups == {
        "System": ["System: Instrument", "System: Process configuration"],
    }
    assert _keys(wb) == [
        "System", "System: Instrument", "System: Process configuration", "Simulation",
        "Parameter Estimation",
    ]
    assert wb._shell.panes["System: Instrument"] is wb.instrument.root
    assert wb._shell.panes["System: Process configuration"] is wb.configuration.root


def test_workbench_edits_components_on_the_instrument_pane():
    wb = WorkbenchWidget()

    assert wb.configuration._components_section.layout.display == "none"
    wb.instrument._components_field.value = ["Salt", "Protein"]

    assert wb.configuration.components == ["Salt", "Protein"]
    assert wb.configuration.process.component_system.names == ["Salt", "Protein"]


def test_workbench_include_builds_only_the_requested_steps():
    wb = WorkbenchWidget(include=("System", "Process configuration", "Simulation"))

    assert wb.instrument is not None
    assert wb.configuration is not None
    assert wb.solution is not None
    assert wb.parameter_estimation is None
    assert list(wb._shell.panes) == [
        "System: Instrument", "System: Process configuration", "Simulation",
    ]
    assert wb.solution.process is wb.configuration.process


def test_workbench_include_accepts_the_old_step_names():
    wb = WorkbenchWidget(include=("System", "Process configuration", "Simulation"))

    assert wb.instrument is not None and wb.parameter_estimation is None
    assert list(wb._shell.panes) == [
        "System: Instrument", "System: Process configuration", "Simulation",
    ]


def test_workbench_excluding_system_still_builds_a_standalone_configuration():
    wb = WorkbenchWidget(include=("Process configuration", "Simulation"))

    assert wb.instrument is None
    assert wb.configuration.process is not None
    assert wb.solution.process is wb.configuration.process


def test_workbench_include_rejects_unknown_step():
    with pytest.raises(ValueError):
        WorkbenchWidget(include=("Process configuration", "Not A Step"))


def test_workbench_include_rejects_widget_for_excluded_step():
    from cadetgui.widgets.composite import ParameterEstimationWidget

    with pytest.raises(ValueError):
        WorkbenchWidget(
            include=("Process configuration",), parameter_estimation=ParameterEstimationWidget()
        )
