"""Round trips: configuration state, the configuration store, run history and stored runs."""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

import cadetgui.io.configuration_store as configuration_store
import cadetgui.io.run_store as run_store
import pytest
from cadetgui.widgets.instrument import (
    ConfigurationWidget,
    InstrumentWidget,
    RunHistoryWidget,
    SolutionWidget,
)

LWE = "Load–Wash–Elute (LWE)"


def set_store_dir(configuration, path):
    configuration.persistence._store_dir_field.value = str(path)
    configuration.persistence._btn_set_store_dir.click()


def fresh():
    return ConfigurationWidget(instrument=InstrumentWidget())


@pytest.mark.parametrize(
    "edit",
    [
        lambda iw, cw: cw.select_models(
            column="General Rate Model (GRM)", binding="Langmuir", template="Step"
        ),
        lambda iw, cw: cw.select_models(template="Pulse Injection"),
        lambda iw, cw: setattr(iw._unit_checkboxes["column"], "value", False),
        lambda iw, cw: setattr(iw._unit_checkboxes["mixer"], "value", True),
        lambda iw, cw: setattr(cw._multiplex_checkboxes["axial_dispersion"], "value", True),
    ],
    ids=["models", "locked-loop", "no-column", "mixer", "multiplex"],
)
def test_snapshot_apply_state_round_trip(bound, edit):
    iw, cw = bound
    cw.components = ["Salt", "Protein"]
    edit(iw, cw)
    cw.column_form.element("length").value = 0.42
    state = cw.snapshot()

    target = fresh()
    target._apply_state("Imported", state)

    assert target.snapshot() == state
    assert target.config_hash == cw.config_hash
    assert target.config_name == "Imported"
    assert type(target.process) is type(cw.process)
    assert target._instrument._sample_loop_checkbox.disabled == iw._sample_loop_checkbox.disabled
    assert target._column_picker.disabled == cw._column_picker.disabled


def test_loading_a_state_restores_its_method_values_exactly(configuration):
    configuration.components = ["Salt", "Protein"]
    configuration.select_models(template="Pulse Injection", binding="Steric Mass Action (SMA)")
    configuration._model_form.element("c_buffer_a").value = [123.0, 0.0]
    saved = configuration.snapshot()
    configuration._model_form.element("c_buffer_a").value = [77.0, 0.0]

    configuration._apply_state("saved", saved)

    assert configuration.snapshot() == saved


@pytest.mark.parametrize("field", ["template_key", "column_key"])
def test_apply_state_rejects_unregistered_keys(configuration, field):
    state = replace(configuration.snapshot(), **{field: "Removed"})
    with pytest.raises(ValueError, match="isn't registered"):
        configuration._apply_state("x", state)


def test_hash_follows_the_content(configuration):
    first = configuration.config_hash
    configuration._model_form.element("flow_rate").value = 4.4e-6
    assert configuration.config_hash not in (None, first)


def test_save_and_import_by_hash_and_by_file(configuration, isolated_stores, upload):
    configuration.config_name = "Saved Config"
    configuration._model_form.element("flow_rate").value = 7.7e-6
    configuration.persistence._btn_save.click()
    saved_hash = configuration.config_hash

    assert str(isolated_stores) in configuration.persistence.save_status.value
    assert configuration_store.load_from_store(saved_hash) == (
        "Saved Config", configuration.snapshot())

    by_hash = fresh()
    by_hash.persistence._import_hash_field.value = saved_hash
    by_hash.persistence._btn_import_hash.click()
    assert (by_hash.config_name, by_hash.config_hash) == ("Saved Config", saved_hash)

    by_file = fresh()
    path = configuration.persist_to_store()
    upload(by_file.persistence._file_upload, path.name, path.read_bytes())
    assert (by_file.config_name, by_file.config_hash) == ("Saved Config", saved_hash)
    assert by_file.persistence._file_upload.value == ()

    by_hash.import_from_store("deadbeef")
    assert "deadbeef" in by_hash.persistence.save_status.value
    assert by_hash.config_hash == saved_hash


def test_custom_store_dir_is_used_for_save_and_import(configuration, tmp_path):
    custom = tmp_path / "custom" / "nested"
    for cw in (configuration, other := fresh()):
        set_store_dir(cw, custom)
    configuration.config_name = "Custom"
    path = configuration.persist_to_store()

    assert path == configuration_store.config_dir("Custom", store_dir=custom) / path.name
    other.import_from_store(configuration.config_hash)
    assert other.config_name == "Custom"

    blocked = tmp_path / "file"
    blocked.write_text("x")
    other.persistence._store_dir_field.value = str(blocked / "sub")
    other.persistence._btn_set_store_dir.click()
    assert other.persistence.store_dir == custom
    assert "cadetgui-msg-error" in other.persistence.save_status.value

    other.persistence._store_dir_field.value = ""
    other.persistence._btn_set_store_dir.click()
    assert other.persistence.store_dir is None


def test_an_unnamed_configuration_is_not_saved(configuration, isolated_stores):
    configuration.persistence._name_field.value = ""

    configuration.persistence._btn_save.click()

    assert "name" in configuration.persistence.save_status.value.lower()
    assert not list(isolated_stores.rglob("*.h5"))
    assert configuration.name_error("running") == "Give the configuration a name before running."
    with pytest.raises(RuntimeError, match="name"):
        configuration.persist_to_store()


def test_workspace_header_counts_saved_versions_and_runs(solution, configuration, runner):
    header = configuration.workspace_header
    assert header.counts == (0, 0)

    configuration.persistence._btn_save.click()
    assert header.counts == (1, 0)
    solution._btn_run.click()
    runner.error = RuntimeError("boom")
    solution._btn_run.click()
    assert header.counts == (1, 2)
    assert "1 saved version · 2 runs" in header._summary.value

    configuration.persistence._name_field.value = "Another name"
    assert header.counts == (0, 0)


def test_run_history_records_persists_and_reloads(tmp_path):
    history = RunHistoryWidget(store_dir=tmp_path)
    seen = []
    history.add_listener(seen.append)

    ok = history.record("first", result="r1", config_name="Cfg", config_hash="abc")
    bad = history.record("bad", error="boom")
    assert history.selected is bad and seen == [ok, bad]

    persisted = {s.run_id: s for s in run_store.list_runs(store_dir=tmp_path)}
    assert persisted[ok.run_id].config_hash == "abc" and persisted[ok.run_id].ok
    assert persisted[bad.run_id].error == "boom" and not persisted[bad.run_id].ok

    reloaded = RunHistoryWidget()
    reloaded.add_listener(seen.append)
    reloaded.store_dir = tmp_path
    assert [r.label for r in reloaded.runs] == ["first", "bad"]
    assert reloaded.selected is None and reloaded.runs[0].result is None
    reloaded.picker.selected_index = 0
    assert seen[-1] is reloaded.runs[0]


def test_run_history_remove_is_in_memory_only(tmp_path):
    history = RunHistoryWidget(store_dir=tmp_path)
    a, b = history.record("A", result=1), history.record("B", result=2)

    history.remove(b)
    history.remove(RunHistoryWidget().record("X"))

    assert history.runs == [a] and history.selected is None
    assert [row[2]["text"] for row in history.picker.rows] == ["A"]
    assert len(run_store.list_runs(store_dir=tmp_path)) == 2


def test_run_history_folder_set_by_hand_is_reported(tmp_path):
    seen = []
    history = RunHistoryWidget(on_manual_store_dir_change=seen.append)
    history.record("memory only", result=1)
    history.store_dir = tmp_path / "programmatic"

    history.store_dir_field.value = str(tmp_path)
    history.set_store_dir_button.click()
    history.store_dir_field.value = ""
    history.set_store_dir_button.click()

    assert seen == [tmp_path.resolve(), None]
    assert history.store_dir is None and history.runs == []


def test_a_run_is_tagged_saved_and_reloaded_in_a_fresh_session(solution, configuration, tmp_path):
    configuration.config_name = "Persisted"
    set_store_dir(configuration, tmp_path)
    runs_dir = configuration_store.runs_dir("Persisted", store_dir=tmp_path)
    assert solution.history.store_dir == runs_dir
    solution._btn_run.click()
    run = solution.history.selected
    assert (run.label, run.config_name, run.config_hash) == (
        "Persisted", "Persisted", configuration.config_hash)
    assert configuration_store.load_from_store(run.config_hash, store_dir=tmp_path)[1] == (
        configuration.snapshot())
    assert run_store.run_output_path(run.run_id, store_dir=solution.history.store_dir).exists()

    cw2 = fresh()
    sw2 = SolutionWidget()
    sw2.bind_to_config(cw2)
    cw2.config_name = "Persisted"
    set_store_dir(cw2, tmp_path)
    assert len(sw2.history.runs) == 1 and sw2.result is None

    sw2.history.picker.selected_index = 0

    assert sw2.result is not None
    assert set(sw2.result.solution) == set(solution.result.solution)
    assert cw2.config_hash == run.config_hash


def test_load_configuration_reimports_the_runs_configuration(solution, configuration):
    solution._btn_run.click()
    saved = solution.history.selected.config_hash
    configuration._model_form.element("flow_rate").value = 9.9e-6

    solution._btn_load_config.click()

    assert configuration.config_hash == saved


def test_delete_needs_confirmation_and_removes_the_runs_files(solution, runner):
    solution._btn_run.click()
    runner.error = RuntimeError("boom")
    solution._btn_run.click()
    store = solution.history.store_dir
    keep, drop = solution.history.runs

    solution._btn_delete_run.click()
    solution._btn_clear.click()
    solution._btn_delete_run.click()
    assert len(solution.history.runs) == 2
    solution._btn_delete_run.click()

    assert solution.history.runs == [keep]
    assert [r.run_id for r in run_store.list_runs(store_dir=store)] == [keep.run_id]
    assert solution.result is None and solution._btn_delete_run.disabled

    solution.history.picker.selected_index = 0
    solution._btn_delete_run.click()
    solution._btn_delete_run.click()
    assert run_store.list_runs(store_dir=store) == []
    assert not run_store.run_output_path(keep.run_id, store_dir=store).exists()


@pytest.mark.parametrize(
    ("plots", "csv", "all_ports"), [(True, True, True), (False, True, True), (True, False, False)]
)
def test_save_outputs_writes_plots_and_data_named_by_run(solution, plots, csv, all_ports):
    from cadetgui.process_model.signals import classify_signal_ports

    solution._btn_run.click()
    solution._save_outputs_plots_checkbox.value = plots
    solution._save_outputs_csv_checkbox.value = csv
    solution._save_outputs_scope.value = "__all__" if all_ports else solution.view.picker.value

    solution._btn_confirm_save_outputs.click()

    files = list((solution.history.store_dir / "results").glob("*"))
    ports = len(classify_signal_ports(solution.result)) if all_ports else 1
    assert len(files) == ports * (plots + csv)
    assert all(f.name.startswith(solution.history.selected.run_id) for f in files)


def test_save_outputs_needs_a_result_and_a_folder(runner):
    sw = SolutionWidget(runner=runner, process=object())
    sw._btn_confirm_save_outputs.click()
    assert "No result" in sw._save_outputs_status.value
    sw._btn_run.click()
    sw._btn_confirm_save_outputs.click()
    assert "storage folder" in sw._save_outputs_status.value.lower()
    sw.history.store_dir = sw_dir = Path(tempfile.mkdtemp())
    sw._save_outputs_plots_checkbox.value = False
    sw._btn_confirm_save_outputs.click()
    assert "Nothing selected" in sw._save_outputs_status.value
    assert not (sw_dir / "results").exists()
