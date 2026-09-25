from __future__ import annotations

import warnings

import matplotlib
import pytest

matplotlib.use("Agg")  # headless test environment, no display needed

import cadetgui.configuration_store as configuration_store
from cadetgui.cadetprocessadapter import INSTRUMENT_TEMPLATES, classify_signal_ports
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


def built_process_with_instrument():
    """Like `built_process()`, but through a Pulse Injection template with its sample loop."""
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    cw._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
    return cw.process


def test_solutionwidget_starts_with_no_process():
    sw = SolutionWidget()
    assert sw.process is None
    assert "No process set" in sw._process_label.value


def test_solutionwidget_set_process_updates_label():
    sw = SolutionWidget()
    sw.set_process(built_process_with_instrument())
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


def test_solutionwidget_bind_to_config_adopts_an_already_set_store_dir(tmp_path):
    cw = built_configuration()
    cw.persistence.store_dir = tmp_path / "project"
    (tmp_path / "project").mkdir()

    sw = SolutionWidget()
    sw.bind_to_config(cw)

    expected = configuration_store.config_dir(cw.config_name, store_dir=tmp_path / "project")
    assert sw.history.store_dir == expected


def test_solutionwidget_bind_to_config_defaults_to_the_configuration_folder_even_unset(tmp_path):
    # `default_store_dir` is monkeypatched to `tmp_path` by `_isolated_store` --
    # so this exercises "the configuration folder itself defaults to a real
    # folder" without the user (or the test) ever setting one explicitly.
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    expected = configuration_store.config_dir(cw.config_name, store_dir=None)
    assert sw.history.store_dir == expected


def test_solutionwidget_bind_to_config_follows_later_store_dir_changes(tmp_path):
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)

    cw.persistence._store_dir_field.value = str(tmp_path / "project")
    cw.persistence._on_set_store_dir(None)

    expected = configuration_store.config_dir(cw.config_name, store_dir=tmp_path / "project")
    assert sw.history.store_dir == expected


def test_solutionwidget_bind_to_config_does_not_override_an_explicit_history_folder(tmp_path):
    # The override has to come through the run history's own "Set folder" UI
    # -- a bare `history.store_dir = ...` assignment is what the auto-follow
    # sync itself uses, so it can't be what distinguishes a deliberate
    # override (see `_on_history_store_dir_manually_set`).
    own_dir = tmp_path / "runs-only"
    own_dir.mkdir()
    cw = built_configuration()

    sw = SolutionWidget()
    sw.history._store_dir_field.value = str(own_dir)
    sw.history._on_set_store_dir(None)
    sw.bind_to_config(cw)

    cw.persistence._store_dir_field.value = str(tmp_path / "project")
    cw.persistence._on_set_store_dir(None)

    assert sw.history.store_dir == own_dir.resolve()


def test_solutionwidget_resuming_auto_follow_by_clearing_the_override(tmp_path):
    own_dir = tmp_path / "runs-only"
    own_dir.mkdir()
    cw = built_configuration()
    cw.persistence.store_dir = tmp_path / "project"
    (tmp_path / "project").mkdir()

    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw.history._store_dir_field.value = str(own_dir)
    sw.history._on_set_store_dir(None)
    assert sw.history.store_dir == own_dir.resolve()

    sw.history._store_dir_field.value = ""
    sw.history._on_set_store_dir(None)

    expected = configuration_store.config_dir(cw.config_name, store_dir=tmp_path / "project")
    assert sw.history.store_dir == expected


def test_solutionwidget_history_store_dir_follows_a_live_rename(tmp_path):
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    first = sw.history.store_dir

    cw.persistence._name_field.value = "Renamed Config"

    expected = configuration_store.config_dir("Renamed Config", store_dir=None)
    assert sw.history.store_dir == expected
    assert sw.history.store_dir != first


def test_solutionwidget_history_store_dir_stops_following_once_overridden(tmp_path):
    own_dir = tmp_path / "runs-only"
    own_dir.mkdir()
    cw = built_configuration()
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw.history._store_dir_field.value = str(own_dir)
    sw.history._on_set_store_dir(None)

    cw.persistence._name_field.value = "Renamed Config"

    assert sw.history.store_dir == own_dir.resolve()


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


def test_solutionwidget_save_options_panel_starts_hidden():
    sw = SolutionWidget(process=built_process())
    assert sw._save_options_box.layout.display == "none"

    sw._on_toggle_save_options(None)
    assert sw._save_options_box.layout.display == ""
    assert sw._btn_save_options.description == "Hide Save Options"


def test_solutionwidget_save_options_button_uses_a_chevron_not_a_save_icon():
    # The floppy-disk icon belongs on the button that actually saves
    # something (_btn_confirm_save_outputs); this one only expands a panel.
    sw = SolutionWidget()
    assert sw._btn_save_options.icon == "chevron-down"
    assert sw._btn_confirm_save_outputs.icon == "save"


def test_solutionwidget_layout_places_save_options_below_the_plot():
    sw = SolutionWidget()
    children = list(sw.root.children)
    assert children.index(sw._plot_out) < children.index(sw._btn_save_options)
    assert children.index(sw._btn_save_options) < children.index(sw._save_options_box)


def test_solutionwidget_save_options_panel_contains_the_storage_folder_field():
    # The folder override and the save-outputs controls live in one combined
    # panel now, not two separate "Show details"/"Save simulation outputs"
    # toggles.
    sw = SolutionWidget(process=built_process())
    assert sw.history._store_dir_field in sw._save_options_box.children[0].children
    assert sw.history._btn_set_store_dir in sw._save_options_box.children[0].children


def test_solutionwidget_running_alone_saves_nothing_on_disk(tmp_path):
    # Confirming the save button is a separate, on-demand action -- not
    # something that fires automatically just because a store_dir is set.
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    assert not (tmp_path / "results").exists()


def test_solutionwidget_save_outputs_all_signals_both_types(tmp_path):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    sw._save_outputs_plots_checkbox.value = True
    sw._save_outputs_csv_checkbox.value = True
    sw._save_outputs_scope.value = "__all__"
    sw._on_confirm_save_outputs(None)

    results_dir = tmp_path / "results"
    pngs = list(results_dir.glob("*.png"))
    csvs = list(results_dir.glob("*.csv"))
    # "All outputs" saves every port, not just the ones the dropdown offers.
    n_signals = len(classify_signal_ports(sw.result))
    assert n_signals > len(sw._signal_picker.option_labels)
    assert len(pngs) == n_signals
    assert len(csvs) == n_signals
    assert "Saved" in sw._save_outputs_status.value
    assert str(results_dir) in sw._save_outputs_status.value


def test_solutionwidget_save_outputs_csv_only(tmp_path):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    sw._save_outputs_plots_checkbox.value = False
    sw._save_outputs_csv_checkbox.value = True
    sw._save_outputs_scope.value = "__all__"
    sw._on_confirm_save_outputs(None)

    results_dir = tmp_path / "results"
    assert list(results_dir.glob("*.png")) == []
    assert len(list(results_dir.glob("*.csv"))) == len(classify_signal_ports(sw.result))


def test_solutionwidget_save_outputs_specific_signal_only(tmp_path):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    specific = sw._signal_picker.value  # the default-selected (sink) signal
    sw._save_outputs_plots_checkbox.value = True
    sw._save_outputs_csv_checkbox.value = False
    sw._save_outputs_scope.value = specific
    sw._on_confirm_save_outputs(None)

    results_dir = tmp_path / "results"
    assert len(list(results_dir.glob("*.png"))) == 1
    assert list(results_dir.glob("*.csv")) == []


def test_solutionwidget_save_outputs_does_nothing_when_neither_type_is_selected(tmp_path):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)

    sw._save_outputs_plots_checkbox.value = False
    sw._save_outputs_csv_checkbox.value = False
    sw._on_confirm_save_outputs(None)

    assert not (tmp_path / "results").exists()
    assert "Nothing selected" in sw._save_outputs_status.value


def test_solutionwidget_save_outputs_without_a_result_shows_an_error():
    sw = SolutionWidget()
    sw._on_confirm_save_outputs(None)

    assert "No result" in sw._save_outputs_status.value


def test_solutionwidget_save_outputs_names_files_by_run_id(tmp_path):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    sw._on_run(None)
    run_id = sw.history.selected.run_id

    sw._save_outputs_plots_checkbox.value = True
    sw._save_outputs_csv_checkbox.value = False
    sw._save_outputs_scope.value = "__all__"
    sw._on_confirm_save_outputs(None)

    pngs = list((tmp_path / "results").glob("*.png"))
    assert pngs
    assert all(p.name.startswith(run_id) for p in pngs)


def test_solutionwidget_save_outputs_without_a_store_dir_shows_an_error():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)  # no store_dir set

    sw._on_confirm_save_outputs(None)

    assert "storage folder" in sw._save_outputs_status.value.lower()


def test_signal_list_collapses_inlet_and_outlet_units_to_one_entry_each():
    # An LCFlowSheet has many Inlet units (buffer_a..d, feed_inlet) and two
    # Outlets (outlet, waste); non-Inlet/Outlet units (column, tubing, mixer)
    # still expose both raw ports.
    sw = SolutionWidget(process=built_process_with_instrument())
    sw._on_run(None)

    # The classification itself -- the dropdown then narrows it to measurable
    # positions (see test_signal_dropdown_offers_only_measurable_positions).
    labels = [label for label, _ in classify_signal_ports(sw.result)]
    assert "outlet: Sink" in labels
    assert "waste: Sink" in labels
    assert "buffer_a: Source" in labels
    assert "feed_inlet: Source" in labels
    assert "column: inlet" in labels
    assert "column: outlet" in labels
    assert labels[0] == "outlet: Sink"  # sorted first -- the common default signal


def test_signal_list_source_and_sink_options_point_at_the_real_port():
    sw = SolutionWidget(process=built_process_with_instrument())
    sw._on_run(None)

    options = dict(classify_signal_ports(sw.result))
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

    process = built_process_with_instrument()
    result = run_process(process)
    options = dict(classify_signal_ports(result))
    assert options["feed_inlet: Source"] == ("feed_inlet", "outlet")
    assert options["column: inlet"] == ("column", "inlet")


def test_solutionwidget_selection_persists_across_reruns():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)
    assert len(sw._signal_picker.option_labels) > 1
    sw._signal_picker.selected_index = 1
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


def test_solutionwidget_run_picker_and_load_config_button_share_one_row():
    sw = SolutionWidget()
    history_row = next(
        c for c in sw.root.children if sw._btn_load_config in getattr(c, "children", ())
    )
    assert sw.history._picker in history_row.children


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

    # Fresh instances, same folder -- nothing carried over in memory. The
    # history lists the run but opens fresh; picking it hydrates it.
    cw2 = built_configuration()
    cw2.persistence.store_dir = tmp_path
    sw2 = SolutionWidget()
    sw2.bind_to_config(cw2)
    sw2.history.store_dir = tmp_path

    assert sw2.history.selected is None
    assert sw2.result is None
    assert len(sw2.history.runs) == 1
    sw2.history._picker.selected_index = 0

    reloaded_run = sw2.history.selected
    assert reloaded_run.label == "Persisted Config"
    assert reloaded_run.result is not None
    assert set(reloaded_run.result.solution.keys()) == set(original_run.result.solution.keys())
    assert sw2.result is not None


def test_solutionwidget_plots_a_run_in_the_interactive_chart():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    assert sw._chart.layout.display == ""
    assert sw._plot_out.layout.display == "none"
    assert len(sw._chart.series) == len(sw.result.process.component_system.names)
    assert sw._chart.series[0]["times"][-1] == sw.result.solution["outlet"]["inlet"].time[-1] / 60


def test_solutionwidget_clear_empties_and_hides_the_chart():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    sw._on_clear(None)

    assert sw._chart.series == []
    assert sw._chart.layout.display == "none"


def _persisted_run_dir(tmp_path, n=2):
    sw = SolutionWidget(process=built_process())
    sw.history.store_dir = tmp_path
    for _ in range(n):
        sw._on_run(None)
    return sw


def test_solutionwidget_opens_fresh_when_the_folder_has_saved_runs(tmp_path):
    _persisted_run_dir(tmp_path)

    sw2 = SolutionWidget(process=built_process())
    sw2.history.store_dir = tmp_path

    assert len(sw2.history.runs) == 2
    assert sw2.history.selected is None
    assert sw2.result is None
    assert sw2._chart.series == []
    assert sw2._chart.layout.display == "none"
    assert sw2._btn_delete_run.disabled is True


def test_solutionwidget_bound_to_a_config_with_saved_runs_opens_fresh(tmp_path):
    cw = built_configuration()
    cw.persistence.store_dir = tmp_path
    sw = SolutionWidget()
    sw.bind_to_config(cw)
    sw._on_run(None)

    cw2 = built_configuration()
    cw2.persistence.store_dir = tmp_path
    sw2 = SolutionWidget()
    sw2.bind_to_config(cw2)

    assert len(sw2.history.runs) == 1
    assert sw2.history.selected is None
    assert sw2.result is None


def test_solutionwidget_delete_button_follows_the_selection(tmp_path):
    sw = _persisted_run_dir(tmp_path)
    assert sw._btn_delete_run.disabled is False

    sw2 = SolutionWidget(process=built_process())
    sw2.history.store_dir = tmp_path
    assert sw2._btn_delete_run.disabled is True
    sw2.history._picker.selected_index = 0
    assert sw2._btn_delete_run.disabled is False


def test_solutionwidget_delete_needs_a_second_click_to_confirm(tmp_path):
    import cadetgui.run_store as run_store

    sw = _persisted_run_dir(tmp_path, n=1)

    sw._on_delete_run(None)

    assert sw._btn_delete_run.description == "Confirm delete?"
    assert len(sw.history.runs) == 1
    assert len(run_store.list_runs(store_dir=tmp_path)) == 1


def test_solutionwidget_delete_confirmation_reverts_on_selection_change(tmp_path):
    sw = _persisted_run_dir(tmp_path)
    sw._on_delete_run(None)

    sw.history._picker.selected_index = 0

    assert sw._btn_delete_run.description == "Delete run"
    sw._on_delete_run(None)
    assert len(sw.history.runs) == 2


def test_solutionwidget_delete_confirmation_reverts_when_another_button_is_clicked(tmp_path):
    sw = _persisted_run_dir(tmp_path, n=1)
    sw._on_delete_run(None)

    sw._on_clear(None)

    assert sw._btn_delete_run.description == "Delete run"
    assert len(sw.history.runs) == 1


def test_solutionwidget_confirmed_delete_removes_run_files_and_clears_the_view(tmp_path):
    import cadetgui.run_store as run_store

    sw = _persisted_run_dir(tmp_path)
    keep, drop = sw.history.runs
    assert run_store.run_output_path(drop.run_id, store_dir=tmp_path).exists()
    notified = []
    sw.add_listener(lambda: notified.append(sw.result))

    sw._on_delete_run(None)
    sw._on_delete_run(None)

    assert sw.history.runs == [keep]
    assert sw.history.selected is None
    assert [r.run_id for r in run_store.list_runs(store_dir=tmp_path)] == [keep.run_id]
    assert not run_store.run_output_path(drop.run_id, store_dir=tmp_path).exists()
    assert run_store.run_output_path(keep.run_id, store_dir=tmp_path).exists()
    assert sw.result is None
    assert sw._chart.series == []
    assert sw._chart.layout.display == "none"
    assert sw.status.value == "<em>Ready.</em>"
    assert notified[-1] is None
    assert sw._btn_delete_run.disabled is True
    assert sw._btn_delete_run.description == "Delete run"
    assert sw._btn_load_config.layout.display == "none"


def test_solutionwidget_delete_a_failed_run_removes_its_manifest(tmp_path):
    import cadetgui.run_store as run_store

    def boom(process, **_kwargs):
        raise RuntimeError("nope")

    sw = SolutionWidget(process=built_process(), runner=boom)
    sw.history.store_dir = tmp_path
    sw._on_run(None)
    assert len(run_store.list_runs(store_dir=tmp_path)) == 1

    sw._on_delete_run(None)
    sw._on_delete_run(None)

    assert run_store.list_runs(store_dir=tmp_path) == []
    assert sw.history.runs == []
    assert sw.status.value == "<em>Ready.</em>"


def test_signal_dropdown_offers_only_measurable_positions():
    sw = SolutionWidget(process=built_process())
    sw._on_run(None)

    labels = sw._signal_picker.option_labels

    assert labels[0] == "outlet: Sink"
    assert "column: outlet" in labels
    assert not any(label.endswith("Source") for label in labels)
    assert not any(label.startswith("mixer") for label in labels)
    assert not any(label.endswith((": inlet", ": volume")) for label in labels)
