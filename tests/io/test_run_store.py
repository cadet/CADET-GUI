"""Run store and the generic record store underneath it."""

from __future__ import annotations

import os
from dataclasses import dataclass

import cadetgui.io.run_store as run_store
import pytest
from cadetgui.io.record_store import (
    delete_record,
    list_records,
    load_record,
    save_record,
)


@dataclass
class Thing:
    id: str
    value: int


def _age(path, seconds):
    stat = path.stat()
    os.utime(path, (stat.st_atime - seconds, stat.st_mtime - seconds))


def test_record_store_round_trips_lists_newest_first_and_deletes(tmp_path):
    save_record("thing", "a", Thing("a", 1), tmp_path)
    save_record("thing", "b", Thing("b", 2), tmp_path)
    save_record("other", "a", Thing("a", 3), tmp_path)
    _age(tmp_path / "thing_a.json", 10)
    (tmp_path / "thing_broken.json").write_text("not json")
    (tmp_path / "thing_wrong_shape.json").write_text('{"unexpected": 1}')

    assert load_record("thing", "a", Thing, tmp_path) == Thing("a", 1)
    assert [r.id for r in list_records("thing", Thing, tmp_path)] == ["b", "a"]
    assert [r.value for r in list_records("other", Thing, tmp_path)] == [3]

    assert delete_record("thing", "a", tmp_path) is True
    assert delete_record("thing", "a", tmp_path) is False
    with pytest.raises(FileNotFoundError):
        load_record("thing", "a", Thing, tmp_path)


def test_run_ids_are_unique_and_sortable_timestamps():
    a, b = run_store.new_run_id(), run_store.new_run_id()
    assert a != b
    date, time, _ = a.split("_")
    assert (len(date), len(time)) == (8, 6)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok": True, "config_hash": "abc123", "config_name": "My Config"},
        {"ok": False, "error": "boom"},
    ],
    ids=["ok", "failed"],
)
def test_save_and_load_run_round_trips_metadata(kwargs):
    run_id = run_store.new_run_id()

    saved = run_store.save_run(run_id, "My Run", **kwargs)

    assert run_store.load_run(run_id) == saved
    assert run_store.list_runs() == [saved]
    assert (saved.ok, saved.error) == (kwargs["ok"], kwargs.get("error"))


def test_load_run_results_rejects_failed_or_missing_output(pulse_process):
    failed, missing = run_store.new_run_id(), run_store.new_run_id()
    run_store.save_run(failed, "Bad", ok=False, error="boom")
    run_store.save_run(missing, "No output", ok=True)

    with pytest.raises(ValueError, match="failure"):
        run_store.load_run_results(run_store.load_run(failed), pulse_process)
    with pytest.raises(FileNotFoundError):
        run_store.load_run_results(run_store.load_run(missing), pulse_process)
    with pytest.raises(FileNotFoundError, match="deadbeef"):
        run_store.load_run("deadbeef")


def test_load_run_results_reloads_a_real_simulation(pulse_process):
    from cadetgui.process_model.simulation import run_process

    run_id = run_store.new_run_id()
    output = run_store.run_output_path(run_id)
    live = run_process(pulse_process, file_path=output)
    run_store.save_run(run_id, "Real", ok=True)

    reloaded = run_store.load_run_results(run_store.load_run(run_id), pulse_process)

    assert reloaded.solution.keys() == live.solution.keys()


def test_delete_run_removes_only_that_runs_files():
    keep, drop = run_store.new_run_id(), run_store.new_run_id()
    for run_id in (keep, drop):
        run_store.save_run(run_id, "r", ok=True)
        run_store.run_output_path(run_id).write_bytes(b"h5")
    config = run_store.default_run_store_dir() / "config_abc.h5"
    config.write_bytes(b"cfg")

    assert run_store.delete_run(drop) is True
    assert run_store.delete_run(drop) is False

    assert [r.run_id for r in run_store.list_runs()] == [keep]
    assert not run_store.run_output_path(drop).exists()
    assert run_store.run_output_path(keep).exists() and config.exists()
    with pytest.raises(ValueError):
        run_store.delete_run("../evil")
