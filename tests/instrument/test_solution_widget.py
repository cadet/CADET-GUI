"""SolutionWidget wiring with a stub runner, DataImportWidget, and end-to-end simulations."""
from __future__ import annotations

import ipywidgets as W
import numpy as np
import pytest
from cadetgui.io import configuration_store
from cadetgui.widgets.instrument import DataImportWidget, SolutionWidget


def test_run_without_a_process_or_name_is_refused(solution, configuration, runner):
    configuration.persistence._name_field.value = ""
    solution._btn_run.click()
    assert "name" in solution.status.value.lower() and runner.calls == []

    unbound = SolutionWidget(runner=runner)
    unbound._btn_run.click()
    assert "No process" in unbound.status.value and runner.calls == []


def test_solution_follows_the_configurations_builds(solution, configuration, runner):
    assert solution.process is configuration.process
    configuration._model_form.element("flow_rate").value = 5e-6
    assert solution.process is configuration.process

    solution._btn_run.click()
    assert runner.calls == [configuration.process]
    configuration.persistence._name_field.value = "Renamed"
    assert "Renamed" in solution._process_label.value


def test_a_run_shows_the_measurable_signals_and_notifies(solution, runner):
    seen = []
    solution.add_listener(lambda: seen.append(solution.result))

    solution._btn_run.click()

    picker = solution.view.picker
    assert solution.result is runner.result and seen[-1] is runner.result
    assert picker.value == ("outlet", "inlet") and picker.option_labels[0] == "Outlet"
    assert {"Column inlet", "Column outlet"} <= set(picker.option_labels)
    assert not any(label.startswith(("Mixer", "Buffer C")) for label in picker.option_labels)
    assert solution.view.chart.series

    picker.selected_index = 1
    picked = picker.value
    solution._btn_run.click()
    assert picker.value == picked

    solution._btn_clear.click()
    assert solution.result is None and seen[-1] is None
    assert solution.view.chart.series == []


def test_history_switches_between_good_and_failed_runs(solution, runner):
    solution._btn_run.click()
    runner.error = RuntimeError("boom")
    solution._btn_run.click()
    good, failed = solution.history.runs

    assert not failed.ok and solution.result is None
    assert "boom" in solution.status.value and not solution._btn_run.disabled
    solution.history.picker.selected_index = 0
    assert solution.result is good.result and "Viewing" in solution.status.value
    solution.history.picker.selected_index = 1
    assert solution.view.picker.option_labels == []


def test_unbound_runs_are_untagged_and_not_stored(runner, pulse_process):
    sw = SolutionWidget(process=pulse_process, runner=runner)
    sw._btn_run.click()
    run = sw.history.selected
    assert (run.config_name, run.config_hash, run.run_id) == (None, None, None)
    assert sw._btn_load_config.layout.display == "none"


def test_history_folder_follows_the_configuration_until_set_by_hand(solution, configuration,
                                                                    tmp_path):
    def expected(store_dir=None):
        return configuration_store.runs_dir(configuration.config_name, store_dir=store_dir)

    assert solution.history.store_dir == expected()
    configuration.persistence._name_field.value = "Renamed"
    assert solution.history.store_dir == expected()
    configuration.persistence._store_dir_field.value = str(tmp_path / "project")
    configuration.persistence._btn_set_store_dir.click()
    assert solution.history.store_dir == expected(tmp_path / "project")

    solution.history.store_dir_field.value = str(tmp_path / "own")
    solution.history.set_store_dir_button.click()
    configuration.persistence._name_field.value = "Again"
    assert solution.history.store_dir == (tmp_path / "own").resolve()

    solution.history.store_dir_field.value = ""
    solution.history.set_store_dir_button.click()
    assert solution.history.store_dir == expected(tmp_path / "project")


SIMPLE = "time,signal\n0,0.0\n1,0.5\n2,1.0\n"
MULTI = "Time [s],Conductivity [mS/cm],Absorbance [mAU]\n0,1.9,0\n10,1.9,5\n20,1.9,10\n"
AKTA = (
    "BLOCK1,,BLOCK2,\nUV_1_280,,Run Log,\nmL,AU,mL,\n"
    "0,0.0,1.0,Phase Elution\n5,1.0,,\n10,2.0,,\n15,1.0,,\n"
)


@pytest.mark.parametrize(
    ("unit", "csv", "time_min", "signal"),
    [
        ("min", SIMPLE, [0.0, 1.0, 2.0], [0.0, 0.5, 1.0]),
        ("s", "time,signal\n0,0.0\n60,1.0\n120,0.5\n", [0.0, 1.0, 2.0], [0.0, 1.0, 0.5]),
        ("min", "time,signal\n0,0.0\nnot,a,number\n2,1.0\n", [0.0, 2.0], [0.0, 1.0]),
    ],
)
def test_two_column_csv_is_imported_directly(upload, unit, csv, time_min, signal):
    di = DataImportWidget()
    di._time_unit.value = unit
    upload(di._upload, "run1.csv", csv)

    (ds,) = di.datasets
    assert ds.label == "run1"
    assert ds.time_min.tolist() == time_min and ds.signal.tolist() == signal


def test_unparseable_file_reports_an_error(upload):
    di = DataImportWidget()
    upload(di._upload, "empty.csv", "time,signal\n")
    assert di.datasets == [] and "Could not parse" in di.status.value


def panel_parts(di):
    panel = di._mapping_box.children[0]
    dropdowns = [c for c in panel.children if isinstance(c, W.Dropdown)]
    flow_rate = panel.children[-2].children[0]
    import_button, cancel_button = panel.children[-1].children
    return dropdowns, flow_rate, import_button, cancel_button


def test_multi_column_csv_is_mapped_before_import(upload):
    di = DataImportWidget()
    upload(di._upload, "run1.csv", MULTI)
    dropdowns, _, import_button, _ = panel_parts(di)
    assert di.datasets == []
    assert [d.value for d in dropdowns] == ["time_s", "signal", "signal"]

    dropdowns[1].value = "skip"
    import_button.click()

    (ds,) = di.datasets
    assert (ds.label, ds.channel) == ("run1", "Absorbance [mAU]")
    assert ds.time_min.tolist() == pytest.approx([0.0, 10 / 60, 20 / 60])
    assert di._mapping_box.children == ()


def test_akta_export_converts_volume_to_time_with_the_flow_rate(upload):
    di = DataImportWidget()
    upload(di._upload, "run1.csv", AKTA)
    dropdowns, flow_rate, import_button, _ = panel_parts(di)
    assert dropdowns == []

    flow_rate.value = 60.0
    import_button.click()

    (ds,) = di.datasets
    assert ds.channel == "UV_1_280" and ds.run.x_basis == "volume"
    assert ds.time_min.tolist() == pytest.approx([0.0, 5 / 60, 10 / 60, 15 / 60])
    assert ds.run.markers == [(1.0, "Phase Elution")]


def test_datasets_accumulate_and_listeners_see_every_change(upload):
    di = DataImportWidget()
    events = []
    di.add_listener(lambda: events.append([d.label for d in di.datasets]))

    upload(di._upload, "a.csv", SIMPLE)
    upload(di._upload, "b.csv", SIMPLE)
    upload(di._upload, "c.csv", MULTI)
    panel_parts(di)[3].click()
    di._dataset_picker.selected_index = 0
    di._btn_remove.click()
    di.clear()

    assert events == [["a"], ["a", "b"], ["a", "b"], ["b"], []]
    assert di._dataset_picker.value is None and di._mapping_box.children == ()


@pytest.mark.slow
def test_a_real_simulation_runs_from_the_configuration(configuration):
    sw = SolutionWidget()
    sw.bind_to_config(configuration)

    sw._btn_run.click()

    outlet = sw.result.solution["outlet"]["inlet"].solution
    assert np.max(outlet) > 0
    assert sw.history.selected.ok


@pytest.mark.slow
def test_generated_code_simulates_to_the_same_outlet(configuration):
    from cadetgui.process_model.simulation import run_process

    configuration.select_models(binding="Linear")
    namespace = {}
    exec(compile(configuration.code(), "<generated>", "exec"), namespace)  # noqa: S102

    widget, script = run_process(configuration.process), run_process(namespace["process"])
    assert np.array_equal(
        widget.solution["outlet"]["inlet"].solution, script.solution["outlet"]["inlet"].solution
    )
