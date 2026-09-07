from __future__ import annotations

import warnings

import matplotlib

matplotlib.use("Agg")  # headless test environment, no display needed

from cadetgui.widgets.composite import ConfigurationWidget, SolutionWidget

warnings.filterwarnings("ignore", category=UserWarning)


def built_process():
    cw = ConfigurationWidget()
    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)
    return cw.process


def test_solutionwidget_starts_with_no_process():
    sw = SolutionWidget()
    assert sw.process is None
    assert "No process set" in sw._process_label.value


def test_solutionwidget_set_process_updates_label():
    sw = SolutionWidget()
    sw.set_process(built_process())
    assert "Batch Elution" in sw._process_label.value


def test_solutionwidget_bind_to_config_tracks_future_builds():
    cw = ConfigurationWidget()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert sw.process is None  # nothing built yet

    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)
    assert sw.process is cw.process


def test_solutionwidget_bind_to_config_picks_up_existing_process():
    cw = ConfigurationWidget()
    cw._column_form._on_apply(None)
    cw._model_form._on_apply(None)

    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert sw.process is cw.process


def test_solutionwidget_run_without_process_shows_error():
    sw = SolutionWidget()
    sw._on_run(None)
    assert sw.result is None
    assert "No process" in sw.status.value


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
