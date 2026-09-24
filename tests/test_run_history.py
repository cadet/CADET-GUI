from __future__ import annotations

import cadetgui.run_store as run_store
from cadetgui.widgets.composite import RunHistoryWidget


def test_record_appends_and_selects_newest():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.record("second", result="r2")

    assert [r.label for r in h.runs] == ["first", "second"]
    assert h.selected.label == "second"
    assert h.selected.result == "r2"


def test_record_marks_ok_vs_error():
    h = RunHistoryWidget()
    ok_run = h.record("ok-run", result=42)
    bad_run = h.record("bad-run", error="boom")

    assert ok_run.ok is True
    assert bad_run.ok is False
    assert "boom" in bad_run.error


def test_picking_a_run_notifies_listeners():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.record("second", result="r2")

    seen = []
    h.add_listener(seen.append)

    h._picker.selected_index = 0
    assert len(seen) == 1
    assert seen[0].label == "first"


def test_picking_the_same_run_again_does_not_renotify():
    h = RunHistoryWidget()
    h.record("only", result="r1")

    seen = []
    h.add_listener(seen.append)
    h._picker.selected_index = 0  # already selected; no real change
    assert seen == []


def test_clear_empties_history():
    h = RunHistoryWidget()
    h.record("first", result="r1")
    h.clear()

    assert h.runs == []
    assert h.selected is None
    assert h._picker.option_labels == []


def test_describe_format_includes_index_and_status():
    h = RunHistoryWidget()
    h.record("MyProcess", result="ok")
    label = h._picker.option_labels[0]
    assert label.startswith("#1")
    assert "MyProcess" in label
    assert label.endswith("ok")


def test_record_carries_config_name_and_hash():
    h = RunHistoryWidget()
    run = h.record("first", result="r1", config_name="My Config", config_hash="abc123")

    assert run.config_name == "My Config"
    assert run.config_hash == "abc123"


def test_record_without_config_leaves_hash_none():
    h = RunHistoryWidget()
    run = h.record("first", result="r1")

    assert run.config_name is None
    assert run.config_hash is None


def test_default_store_dir_is_none_and_nothing_is_persisted(tmp_path, monkeypatch):
    """No store_dir set -> plain in-memory history, matching the pre-persistence behavior."""
    monkeypatch.setattr(run_store, "default_run_store_dir", lambda: tmp_path)
    h = RunHistoryWidget()
    h.record("first", result="r1")

    assert h.store_dir is None
    assert run_store.list_runs(store_dir=tmp_path) == []


def test_record_persists_metadata_when_store_dir_is_set(tmp_path):
    h = RunHistoryWidget(store_dir=tmp_path)
    run = h.record("first", result="r1", config_name="Cfg", config_hash="abc")

    assert run.run_id is not None
    persisted = run_store.list_runs(store_dir=tmp_path)
    assert len(persisted) == 1
    assert persisted[0].run_id == run.run_id
    assert persisted[0].label == "first"
    assert persisted[0].ok is True
    assert persisted[0].config_name == "Cfg"
    assert persisted[0].config_hash == "abc"


def test_record_persists_a_failed_run_too(tmp_path):
    h = RunHistoryWidget(store_dir=tmp_path)
    run = h.record("bad", error="boom")

    persisted = run_store.list_runs(store_dir=tmp_path)
    assert persisted[0].run_id == run.run_id
    assert persisted[0].ok is False
    assert persisted[0].error == "boom"


def test_construction_loads_existing_runs_from_store_dir(tmp_path):
    id_a = run_store.new_run_id()
    run_store.save_run(id_a, "Old Run", ok=True, store_dir=tmp_path)

    h = RunHistoryWidget(store_dir=tmp_path)

    assert [r.label for r in h.runs] == ["Old Run"]
    assert h.runs[0].run_id == id_a
    assert h.runs[0].result is None  # not hydrated -- only metadata was ever stored
    assert h.selected.label == "Old Run"


def test_loaded_run_is_ok_even_though_result_is_still_none(tmp_path):
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "Old Run", ok=True, store_dir=tmp_path)

    h = RunHistoryWidget(store_dir=tmp_path)

    assert h.runs[0].ok is True
    assert h.runs[0].result is None


def test_setting_store_dir_via_the_ui_field_loads_that_folders_history(tmp_path):
    run_store.save_run(run_store.new_run_id(), "From Folder", ok=True, store_dir=tmp_path)

    h = RunHistoryWidget()
    h.record("In memory only", result="r1")
    h._store_dir_field.value = str(tmp_path)
    h._on_set_store_dir(None)

    assert [r.label for r in h.runs] == ["From Folder"]
    assert h.store_dir == tmp_path.resolve()


def test_clearing_the_store_dir_field_reverts_to_in_memory_only(tmp_path):
    h = RunHistoryWidget(store_dir=tmp_path)
    h._store_dir_field.value = ""
    h._on_set_store_dir(None)

    assert h.store_dir is None
    assert h.runs == []


def test_setting_store_dir_via_the_ui_field_fires_the_manual_change_callback(tmp_path):
    seen = []
    h = RunHistoryWidget(on_manual_store_dir_change=seen.append)

    h._store_dir_field.value = str(tmp_path)
    h._on_set_store_dir(None)

    assert seen == [tmp_path.resolve()]


def test_programmatic_store_dir_assignment_does_not_fire_the_manual_change_callback(tmp_path):
    seen = []
    h = RunHistoryWidget(on_manual_store_dir_change=seen.append)

    h.store_dir = tmp_path

    assert seen == []


def test_clearing_the_store_dir_field_fires_the_manual_change_callback_with_none(tmp_path):
    seen = []
    h = RunHistoryWidget(store_dir=tmp_path, on_manual_store_dir_change=seen.append)

    h._store_dir_field.value = ""
    h._on_set_store_dir(None)

    assert seen == [None]


def test_table_rows_show_time_label_and_a_status_chip_per_run():
    h = RunHistoryWidget()
    h.record("good", result=1)
    h.record("bad", error="boom")

    rows = h._picker.rows
    assert [row[0]["text"] for row in rows] == ["1", "2"]
    assert rows[0][2]["text"] == "good"
    assert rows[0][3] == {"text": "ok", "chip": "ok"}
    assert rows[1][3] == {"text": "failed", "chip": "error"}

    h.clear()
    assert h._picker.rows == []
