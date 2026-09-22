from __future__ import annotations

import warnings

import matplotlib
import pytest

matplotlib.use("Agg")  # headless test environment, no display needed

import cadetgui.configuration_store as configuration_store
from cadetgui.simulation import run_process as _default_runner
from cadetgui.widgets.composite import (
    ConfigurationWidget,
    InstrumentWidget,
    SolutionWidget,
)

warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the configuration store to a tmp dir -- never touch the real one."""
    monkeypatch.setattr(configuration_store, "default_store_dir", lambda: tmp_path)


def built_configuration():
    """A default InstrumentWidget + bound ConfigurationWidget, auto-committed."""
    iw = InstrumentWidget()
    return ConfigurationWidget(instrument=iw)


def built_process():
    return built_configuration().process


def test_solutionwidget_starts_with_no_process():
    sw = SolutionWidget()
    assert sw.process is None
    assert "No process set" in sw._process_label.value


def test_solutionwidget_set_process_updates_label():
    sw = SolutionWidget()
    sw.set_process(built_process())
    assert "pulse_injection" in sw._process_label.value


def test_solutionwidget_bind_to_config_tracks_future_field_changes():
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert sw.process is cw.process  # already auto-built by the time we bind

    first_process = cw.process
    cw._model_form.element("flow_rate").value = 5e-6
    assert sw.process is cw.process
    assert sw.process is not first_process  # picked up the fresh auto-rebuild


def test_solutionwidget_bind_to_config_picks_up_existing_process():
    cw = built_configuration()

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
    # An LCFlowSheet has many Inlet units (buffer_a..d, feed_inlet) and two
    # Outlets (outlet, waste); non-Inlet/Outlet units (column, tubing, mixer)
    # still expose both raw ports.
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    labels = sw._signal_picker.option_labels
    assert "outlet: Sink" in labels
    assert "waste: Sink" in labels
    assert "buffer_a: Source" in labels
    assert "feed_inlet: Source" in labels
    assert "column: inlet" in labels
    assert "column: outlet" in labels
    assert labels[0] == "outlet: Sink"  # sorted first -- the common default signal


def test_signal_list_source_and_sink_options_point_at_the_real_port():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    options = dict(sw._signal_picker._options)
    assert options["feed_inlet: Source"] == ("feed_inlet", "outlet")
    assert options["outlet: Sink"] == ("outlet", "inlet")


def test_signal_picker_defaults_to_the_sink():
    # Comparing/fitting against the process outlet is the common case --
    # classify_signal_ports() sorts "Sink" first so it's index 0 by default.
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    assert sw._signal_picker.value == ("outlet", "inlet")


def test_classify_signal_ports_is_usable_standalone_from_the_adapter():
    # SolutionWidget is a thin caller -- the classification itself lives in
    # cadetprocessadapter.py (framework-agnostic, no ipywidgets import).
    from cadetgui.cadetprocessadapter import classify_signal_ports
    from cadetgui.simulation import run_process

    process = built_process()
    result = run_process(process)
    options = dict(classify_signal_ports(result))
    assert options["feed_inlet: Source"] == ("feed_inlet", "outlet")
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


def test_solutionwidget_run_tags_history_with_config_name_and_hash():
    cw = built_configuration()
    cw.persistence._name_field.value = "My Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    run = sw.history.selected
    assert run.config_name == "My Config"
    assert run.config_hash == cw.config_hash


def test_solutionwidget_run_auto_saves_config_to_store():
    cw = built_configuration()
    cw.persistence._name_field.value = "Auto Saved Config"
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
    cw = built_configuration()
    cw.persistence._name_field.value = ""  # cleared the default name
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
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    assert "New Experiment" in sw._process_label.value  # the default name, not "pulse_injection"
    assert "pulse_injection" not in sw._process_label.value

    cw.persistence._name_field.value = "My Named Config"
    assert "My Named Config" in sw._process_label.value
    assert "pulse_injection" not in sw._process_label.value


def test_solutionwidget_run_history_label_uses_the_configuration_name():
    cw = built_configuration()
    cw.persistence._name_field.value = "My Named Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    sw._on_run(None)

    assert sw.history.selected.label == "My Named Config"


def test_solutionwidget_load_config_button_hidden_without_a_hash():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)  # no bound ConfigurationWidget -> no hash

    assert sw._btn_load_config.layout.display == "none"


def test_solutionwidget_load_config_button_reimports_the_run_configuration():
    cw = built_configuration()
    cw.persistence._name_field.value = "Reimport Test Config"
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw._on_run(None)
    saved_hash = sw.history.selected.config_hash

    cw._model_form.element("flow_rate").value = 9.9e-6
    assert cw.config_hash != saved_hash

    assert sw._btn_load_config.layout.display == ""
    sw._on_load_config(None)

    assert cw.config_hash == saved_hash


def test_solutionwidget_run_without_a_store_dir_reserves_no_run_id():
    """Default (no store_dir set): behaves exactly as before -- nothing written to disk."""
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    assert sw.history.selected.run_id is None


def test_solutionwidget_run_with_a_store_dir_persists_the_run(tmp_path):
    import cadetgui.run_store as run_store

    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    run = sw.history.selected
    assert run.run_id is not None
    persisted = run_store.list_runs(store_dir=tmp_path)
    assert persisted[0].run_id == run.run_id
    assert run_store.run_output_path(run.run_id, store_dir=tmp_path).exists()


def test_solutionwidget_reloads_a_persisted_run_in_a_fresh_instance(tmp_path):
    """The real point of the store: a 'kernel restart' (fresh widgets, same folder)
    can still view a previous run's actual result, not just its label."""
    cw = built_configuration()
    cw.persistence._name_field.value = "Persisted Config"
    cw.persistence.store_dir = tmp_path

    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    original_run = sw.history.selected
    assert original_run.result is not None

    # Fresh instances, same folder -- nothing carried over in memory. Pointing
    # the history at the folder auto-selects (and so auto-hydrates) the
    # newest run, the same as picking it by hand would.
    cw2 = built_configuration()
    cw2.persistence.store_dir = tmp_path
    sw2 = SolutionWidget()
    sw2.bind_to_config(cw2)
    sw2.history.store_dir = tmp_path

    reloaded_run = sw2.history.selected
    assert reloaded_run.label == "Persisted Config"
    assert reloaded_run.result is not None
    assert set(reloaded_run.result.solution.keys()) == set(original_run.result.solution.keys())
    assert sw2.result is not None
