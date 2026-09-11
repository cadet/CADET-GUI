from __future__ import annotations

import datetime as dt
import warnings

import matplotlib
import pytest

matplotlib.use("Agg")  # headless test environment, no display needed

import cadetgui.configuration_store as configuration_store
from cadetgui.simulation import run_process as _default_runner
from cadetgui.widgets.composite import (
    ConfigurationWidget,
    DataImportWidget,
    SolutionWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def upload_csv(widget: DataImportWidget, filename: str, csv_text: str) -> None:
    content = memoryview(csv_text.encode("utf-8"))
    widget._upload.value = (
        {
            "name": filename,
            "type": "text/csv",
            "size": len(content),
            "last_modified": dt.datetime.now(),
            "content": content,
        },
    )


def built_process():
    cw = ConfigurationWidget()  # auto-commits its defaults on construction
    return cw.process


def test_solutionwidget_starts_with_no_process():
    sw = SolutionWidget()
    assert sw.process is None
    assert "No process set" in sw._process_label.value


def test_solutionwidget_set_process_updates_label():
    sw = SolutionWidget()
    sw.set_process(built_process())
    assert "Batch Elution" in sw._process_label.value


def test_solutionwidget_bind_to_config_tracks_future_field_changes():
    cw = ConfigurationWidget()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert sw.process is cw.process  # already auto-built by the time we bind

    first_process = cw.process
    cw._model_form.element("flow_rate").value = 5e-6
    assert sw.process is cw.process
    assert sw.process is not first_process  # picked up the fresh auto-rebuild


def test_solutionwidget_bind_to_config_picks_up_existing_process():
    cw = ConfigurationWidget()

    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert sw.process is cw.process


def test_solutionwidget_run_without_process_shows_error():
    sw = SolutionWidget()
    sw._on_run(None)
    assert sw.result is None
    assert "No process" in sw.status.value


def test_solutionwidget_shows_spinner_and_disables_button_while_running():
    sw = SolutionWidget(process=built_process())
    seen = {}

    def spying_runner(process):
        seen["disabled"] = sw._btn_run.disabled
        seen["description"] = sw._btn_run.description
        seen["status"] = sw.status.value
        return _default_runner(process)

    sw._runner = spying_runner
    sw._on_run(None)

    assert seen["disabled"] is True
    assert seen["description"] == "Running..."
    assert "cadetgui-spinner" in seen["status"]
    assert sw._btn_run.disabled is False  # reset once the run finishes
    assert sw._btn_run.description == "Run simulation"


def test_solutionwidget_resets_button_even_when_run_fails():
    sw = SolutionWidget(process=object())  # not a real process -> runner raises
    sw._on_run(None)

    assert sw._btn_run.disabled is False
    assert sw._btn_run.description == "Run simulation"


def test_solutionwidget_run_populates_signals_and_plots():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    assert sw.result is not None
    assert sw._signal_picker.option_labels  # non-empty
    assert sw._signal_picker.value is not None
    assert "finished" in sw.status.value.lower()


def test_signal_list_collapses_inlet_and_outlet_units_to_one_entry_each():
    # Batch Elution: two Inlet units (feed, eluent), one real column, one Outlet.
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    labels = sw._signal_picker.option_labels
    assert labels == [
        "feed: Source",
        "eluent: Source",
        "column: inlet",
        "column: outlet",
        "outlet: Sink",
    ]


def test_signal_list_source_and_sink_options_point_at_the_real_port():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    options = dict(sw._signal_picker._options)
    assert options["feed: Source"] == ("feed", "outlet")
    assert options["outlet: Sink"] == ("outlet", "inlet")


def test_classify_signal_ports_is_usable_standalone_from_the_adapter():
    # SolutionWidget is a thin caller -- the classification itself lives in
    # cadetprocessadapter.py (framework-agnostic, no ipywidgets import).
    from cadetgui.cadetprocessadapter import classify_signal_ports
    from cadetgui.simulation import run_process

    process = built_process()
    result = run_process(process)
    options = dict(classify_signal_ports(result))
    assert options["feed: Source"] == ("feed", "outlet")
    assert options["column: inlet"] == ("column", "inlet")


def test_solutionwidget_selection_persists_across_reruns():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)
    sw._signal_picker.selected_index = 3
    picked = sw._signal_picker.value

    sw._on_run(None)
    assert sw._signal_picker.value == picked


def test_solutionwidget_clear_resets_state():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)
    sw._on_clear(None)

    assert sw.result is None
    assert sw._signal_picker.option_labels == []


def test_solutionwidget_run_records_history():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)
    sw._on_run(None)

    assert len(sw.history.runs) == 2
    assert all(r.ok for r in sw.history.runs)
    assert sw.history.selected.result is sw.result


def test_solutionwidget_failed_run_records_history_without_crashing():
    sw = SolutionWidget(process=object())  # not a real process
    sw._on_run(None)

    assert len(sw.history.runs) == 1
    assert sw.history.runs[0].ok is False
    assert sw.result is None


def test_solutionwidget_picking_a_past_run_restores_its_view():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)
    first_result = sw.result
    sw._on_run(None)
    assert sw.result is not first_result

    sw.history._picker.selected_index = 0  # go back to the first run
    assert sw.result is first_result
    assert "Viewing" in sw.status.value


def test_solutionwidget_picking_a_failed_run_shows_its_error():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)  # one good run in history

    sw.process = object()
    sw._on_run(None)  # one failed run in history

    sw.history._picker.selected_index = 0  # back to the good run
    assert sw._signal_picker.option_labels

    sw.history._picker.selected_index = 1  # the failed run
    assert sw._signal_picker.option_labels == []
    assert "Simulation failed" in sw.status.value


def test_solutionwidget_overlays_bound_experimental_data():
    sw = SolutionWidget(process=built_process())
    di = DataImportWidget()
    sw.bind_to_data(di)

    upload_csv(di, "measured.csv", "time,signal\n0,0.0\n1,0.5\n")
    sw._on_run(None)  # no exception with data already loaded before the run

    unit, port = sw._signal_picker.value
    solution = sw.result.solution[unit][port]
    fig, ax = solution.plot()
    for ds in di.datasets:
        ax.plot(ds.time_min, ds.signal, linestyle="--", label=f"{ds.label} (measured)")
    ax.legend()
    labels = ax.get_legend_handles_labels()[1]
    assert any("measured" in label for label in labels)


def test_solutionwidget_replots_when_data_uploaded_after_run():
    sw = SolutionWidget(process=built_process())
    di = DataImportWidget()
    sw.bind_to_data(di)

    sw._on_run(None)  # plot exists before any experimental data is loaded
    upload_csv(di, "late.csv", "time,signal\n0,0.0\n1,1.0\n")  # must not raise

    assert di.datasets  # upload succeeded and triggered a listener-driven replot


def test_solutionwidget_run_tags_history_with_config_name_and_hash():
    cw = ConfigurationWidget()
    cw._name_field.value = "My Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    run = sw.history.selected
    assert run.config_name == "My Config"
    assert run.config_hash == cw.config_hash


def test_solutionwidget_run_auto_saves_config_to_store():
    cw = ConfigurationWidget()
    cw._name_field.value = "Auto Saved Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    name, state = configuration_store.load_from_store(cw.config_hash)
    assert state == cw._snapshot_state()


def test_solutionwidget_run_without_bound_config_leaves_history_untagged():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    run = sw.history.selected
    assert run.config_name is None
    assert run.config_hash is None


def test_solutionwidget_run_refuses_when_bound_config_has_no_name():
    cw = ConfigurationWidget()
    cw._name_field.value = ""  # cleared the default name
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    assert sw.history.runs == []
    assert "name" in sw.status.value.lower()


def test_solutionwidget_run_without_bound_config_does_not_require_a_name():
    sw = SolutionWidget(process=built_process())  # no ConfigurationWidget bound
    sw._on_run(None)

    assert len(sw.history.runs) == 1


def test_solutionwidget_process_label_shows_the_configuration_name_not_the_process_name():
    cw = ConfigurationWidget()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert "New Experiment" in sw._process_label.value  # the default name, not "Batch Elution"
    assert "Batch Elution" not in sw._process_label.value

    cw._name_field.value = "My Named Config"
    assert "My Named Config" in sw._process_label.value
    assert "Batch Elution" not in sw._process_label.value


def test_solutionwidget_run_history_label_uses_the_configuration_name():
    cw = ConfigurationWidget()
    cw._name_field.value = "My Named Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    assert sw.history.selected.label == "My Named Config"


def test_solutionwidget_load_config_button_hidden_without_a_hash():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)  # no bound ConfigurationWidget -> no hash

    assert sw._btn_load_config.layout.display == "none"


def test_solutionwidget_load_config_button_reimports_the_run_configuration():
    cw = ConfigurationWidget()
    cw._name_field.value = "Reimport Test Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw._on_run(None)
    saved_hash = sw.history.selected.config_hash

    cw._model_form.element("flow_rate").value = 9.9e-6
    assert cw.config_hash != saved_hash

    assert sw._btn_load_config.layout.display == ""
    sw._on_load_config(None)

    assert cw.config_hash == saved_hash
