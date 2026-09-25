from __future__ import annotations

import warnings

import cadetgui.run_store as run_store
import pytest
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget

warnings.filterwarnings("ignore", category=UserWarning)


def built_process():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)  # auto-commits its defaults on construction
    return cw.process


def test_new_run_id_is_unique():
    assert run_store.new_run_id() != run_store.new_run_id()


def test_new_run_id_is_timestamp_readable():
    # Readable/sortable at a glance in a file browser, not an opaque uuid --
    # a fixed-width date/time prefix plus a short disambiguating suffix.
    run_id = run_store.new_run_id()
    date_part, time_part, _suffix = run_id.split("_")
    assert len(date_part) == 8  # YYYYMMDD
    assert len(time_part) == 6  # HHMMSS


def test_save_and_load_run_round_trips_metadata(tmp_path):
    run_id = run_store.new_run_id()
    saved = run_store.save_run(
        run_id, "My Run", ok=True, config_hash="abc123", config_name="My Config",
        store_dir=tmp_path,
    )
    loaded = run_store.load_run(run_id, store_dir=tmp_path)

    assert loaded == saved
    assert loaded.label == "My Run"
    assert loaded.ok is True
    assert loaded.config_hash == "abc123"
    assert loaded.config_name == "My Config"
    assert loaded.error is None


def test_save_run_records_an_error_for_a_failed_run(tmp_path):
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "Bad Run", ok=False, error="boom", store_dir=tmp_path)
    loaded = run_store.load_run(run_id, store_dir=tmp_path)

    assert loaded.ok is False
    assert loaded.error == "boom"


def test_load_run_raises_a_clear_error_for_an_unknown_id(tmp_path):
    with pytest.raises(FileNotFoundError, match="deadbeef"):
        run_store.load_run("deadbeef", store_dir=tmp_path)


def test_list_runs_is_empty_for_a_fresh_store_dir(tmp_path):
    assert run_store.list_runs(store_dir=tmp_path) == []


def test_list_runs_lists_every_saved_run_newest_first(tmp_path):
    id_a = run_store.new_run_id()
    run_store.save_run(id_a, "First", ok=True, store_dir=tmp_path)
    id_b = run_store.new_run_id()
    run_store.save_run(id_b, "Second", ok=True, store_dir=tmp_path)

    runs = run_store.list_runs(store_dir=tmp_path)

    assert [r.run_id for r in runs] == [id_b, id_a]


def test_run_output_path_is_scoped_to_the_given_store_dir(tmp_path):
    run_id = run_store.new_run_id()
    path = run_store.run_output_path(run_id, store_dir=tmp_path)

    assert path == tmp_path / f"run_{run_id}.h5"


def test_run_files_are_prefixed_to_stand_out_from_a_configuration_save(tmp_path):
    # A run's own h5/json and a configuration's saved h5 can live in the same
    # per-configuration folder (see configuration_store.config_dir) -- the
    # "run_" prefix (vs. configuration_store's "config_" prefix) is what
    # makes the two kinds of file tell apart at a glance.
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "My Run", ok=True, store_dir=tmp_path)

    assert (tmp_path / f"run_{run_id}.json").exists()
    assert run_store.run_output_path(run_id, store_dir=tmp_path).name == f"run_{run_id}.h5"


def test_load_run_results_rejects_a_failed_run(tmp_path):
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "Bad Run", ok=False, error="boom", store_dir=tmp_path)
    run = run_store.load_run(run_id, store_dir=tmp_path)

    with pytest.raises(ValueError, match="failure"):
        run_store.load_run_results(run, process=None, store_dir=tmp_path)


def test_load_run_results_raises_when_the_output_file_is_missing(tmp_path):
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "No Output", ok=True, store_dir=tmp_path)
    run = run_store.load_run(run_id, store_dir=tmp_path)

    with pytest.raises(FileNotFoundError):
        run_store.load_run_results(run, process=built_process(), store_dir=tmp_path)


def test_load_run_results_reconstructs_a_real_simulation_result(tmp_path):
    from cadetgui.simulation import run_process

    process = built_process()
    run_id = run_store.new_run_id()
    output_path = run_store.run_output_path(run_id, store_dir=tmp_path)

    live_result = run_process(process, file_path=output_path)
    assert output_path.exists()  # kept, unlike the simulator's own self-deleting tempfile

    run_store.save_run(run_id, "Real Run", ok=True, store_dir=tmp_path)
    run = run_store.load_run(run_id, store_dir=tmp_path)
    reloaded = run_store.load_run_results(run, process, store_dir=tmp_path)

    assert reloaded.solution.keys() == live_result.solution.keys()


def test_delete_run_removes_manifest_and_output_only_for_that_run(tmp_path):
    keep, drop = run_store.new_run_id(), run_store.new_run_id()
    for run_id in (keep, drop):
        run_store.save_run(run_id, "r", ok=True, store_dir=tmp_path)
        run_store.run_output_path(run_id, store_dir=tmp_path).write_bytes(b"h5")
    other = tmp_path / "config_abc.h5"
    other.write_bytes(b"cfg")

    assert run_store.delete_run(drop, store_dir=tmp_path) is True

    assert [r.run_id for r in run_store.list_runs(store_dir=tmp_path)] == [keep]
    assert not run_store.run_output_path(drop, store_dir=tmp_path).exists()
    assert run_store.run_output_path(keep, store_dir=tmp_path).exists()
    assert other.exists()


def test_delete_run_without_an_output_file_or_an_unknown_id_is_fine(tmp_path):
    run_id = run_store.new_run_id()
    run_store.save_run(run_id, "failed", ok=False, error="boom", store_dir=tmp_path)

    assert run_store.delete_run(run_id, store_dir=tmp_path) is True
    assert run_store.delete_run(run_id, store_dir=tmp_path) is False
    assert run_store.list_runs(store_dir=tmp_path) == []


def test_delete_run_rejects_a_path_like_id(tmp_path):
    with pytest.raises(ValueError):
        run_store.delete_run("../evil", store_dir=tmp_path)
