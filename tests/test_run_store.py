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

    assert path == tmp_path / f"{run_id}.h5"


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
