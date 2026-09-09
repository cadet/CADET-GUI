from __future__ import annotations

import datetime as dt
import warnings

import matplotlib

matplotlib.use("Agg")  # headless test environment, no display needed

from cadetgui.simulation import run_process as _default_runner
from cadetgui.widgets.composite import (
    ConfigurationWidget,
    DataImportWidget,
    SolutionWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


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
