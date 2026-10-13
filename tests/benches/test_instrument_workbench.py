"""InstrumentWorkbenchWidget: which widgets it builds and how it wires them."""
from __future__ import annotations

import warnings

import cadetgui.io.configuration_store as configuration_store
import pytest
from cadetgui.widgets.benches import InstrumentWorkbenchWidget
from cadetgui.widgets.estimation import ParameterEstimationWidget
from cadetgui.widgets.instrument import (
    ConfigurationWidget,
    InstrumentWidget,
    SolutionWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)

PANES = ["System: Instrument", "System: Process configuration", "Simulation",
         "Parameter Estimation"]


@pytest.fixture
def bench():
    return InstrumentWorkbenchWidget()


def test_workbench_builds_and_wires_every_step(bench):
    assert list(bench._shell.panes) == PANES
    assert bench._shell.panes["System: Instrument"] is bench.instrument.root
    assert bench.solution.process is bench.configuration.process is not None

    bench.instrument._components_field.value = ["Salt", "Protein"]
    assert bench.solution.process is bench.configuration.process
    assert bench.solution.process.component_system.names == ["Salt", "Protein"]

    bench.instrument._unit_checkboxes["column"].value = False
    assert bench.configuration._column_picker.disabled


def test_estimation_preview_waits_for_its_pane(bench):
    estimation = bench.parameter_estimation
    assert estimation._signal_picker.option_labels
    assert estimation._display_result is None

    bench._shell.show("Parameter Estimation")
    before = estimation._display_result
    assert before is not None
    bench.configuration._model_form.element("flow_rate").value = 2e-6
    assert estimation._display_result is before
    bench._shell.show("Parameter Estimation")
    assert estimation._display_result is not before
    assert bench.solution.result is None


def test_header_sits_above_the_panes_and_drives_the_run_folder(bench, tmp_path):
    header = bench.configuration.workspace_header
    assert bench.root.children[2] is header.root
    assert bench.root.children[3] is bench._shell.body

    header.persistence._store_dir_field.value = str(tmp_path)
    header.persistence._btn_set_store_dir.click()
    assert bench.solution.history.store_dir == configuration_store.runs_dir(
        bench.configuration.config_name, store_dir=tmp_path
    )


@pytest.mark.parametrize(
    ("include", "panes"),
    [
        (("System", "Process configuration", "Simulation"), PANES[:3]),
        (("Process configuration", "Simulation"), PANES[1:3]),
        (("System", "Simulation"), [PANES[0], PANES[2]]),
    ],
)
def test_include_builds_only_the_requested_steps(include, panes):
    bench = InstrumentWorkbenchWidget(include=include)

    assert list(bench._shell.panes) == panes
    assert (bench.instrument is None) == ("System" not in include)
    assert bench.parameter_estimation is None
    if bench.configuration is not None:
        assert bench.configuration.process is not None
        assert bench.solution.process is bench.configuration.process
    else:
        assert len(bench.root.children) == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"include": ("Process configuration", "Not A Step")},
        {"include": ("Process configuration",), "parameter_estimation": None},
    ],
)
def test_include_rejects_unknown_steps_and_widgets_for_skipped_steps(kwargs):
    if "parameter_estimation" in kwargs:
        kwargs["parameter_estimation"] = ParameterEstimationWidget()
    with pytest.raises(ValueError):
        InstrumentWorkbenchWidget(**kwargs)


def test_prebuilt_widgets_are_wired_and_left_in_place():
    instrument = InstrumentWidget()
    configuration = ConfigurationWidget()
    solution = SolutionWidget()

    bench = InstrumentWorkbenchWidget(
        instrument=instrument, configuration=configuration, solution=solution
    )

    assert (bench.instrument, bench.configuration, bench.solution) == (
        instrument, configuration, solution)
    assert configuration.flow_sheet is instrument.flow_sheet
    assert solution.process is configuration.process
    assert bench.root.children[2] is bench._shell.body


@pytest.mark.parametrize("starting_values", [True, False])
def test_starting_values_switch_reaches_the_configuration(starting_values):
    bench = InstrumentWorkbenchWidget(
        include=["System", "Process configuration"], starting_values=starting_values
    )
    assert bench.configuration.use_starting_values is starting_values
