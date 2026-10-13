"""Configuration store: content hash, H5 round trips, store folders and listing."""

from __future__ import annotations

import pytest
from cadet import H5
from cadetgui.io.configuration_store import (
    compute_hash,
    config_dir,
    list_store,
    load_from_store,
    load_h5,
    runs_dir,
    safe_config_dirname,
    save_h5,
    save_to_store,
)


def _write_plain_h5(path):
    h5 = H5()
    h5.root.some_other_data = 1
    h5.filename = str(path)
    h5.save()


def test_hash_ignores_key_order_and_changes_with_content(make_state):
    a = make_state(column_values={"length": 0.5, "diameter": 0.024})
    assert compute_hash(a) == compute_hash(
        make_state(column_values={"diameter": 0.024, "length": 0.5})
    )
    assert compute_hash(a) != compute_hash(make_state(column_values={"length": 0.6}))


@pytest.mark.parametrize("standalone", [False, True], ids=["instrument", "standalone"])
def test_h5_round_trips_the_full_state(make_state, tmp_path, standalone):
    state = make_state(instrument=None) if standalone else make_state()
    path = tmp_path / "config.h5"

    save_h5(state, "My Config", path)

    assert load_h5(path) == ("My Config", state)


def test_load_h5_ignores_unknown_keys_and_rejects_a_foreign_file(make_state, tmp_path):
    path = tmp_path / "legacy.h5"
    save_h5(make_state(), "Legacy", path)
    h5 = H5()
    h5.filename = str(path)
    h5.load_from_file()
    h5.root.cadetgui.state.instrument.use_lc_system = False
    h5.save()
    assert load_h5(path) == ("Legacy", make_state())

    _write_plain_h5(tmp_path / "plain.h5")
    with pytest.raises(ValueError, match="cadetgui"):
        load_h5(tmp_path / "plain.h5")


def test_store_saves_by_content_hash_in_a_folder_per_name(make_state, tmp_path):
    state = make_state()
    path = save_to_store(state, "Name A", store_dir=tmp_path)
    assert path == tmp_path / "Name_A" / f"config_{compute_hash(state)}.h5"

    assert save_to_store(state, "Name B", store_dir=tmp_path) == path
    assert not (tmp_path / "Name_B").exists()
    assert load_from_store(compute_hash(state), store_dir=tmp_path) == ("Name B", state)

    with pytest.raises(FileNotFoundError, match="deadbeef"):
        load_from_store("deadbeef", store_dir=tmp_path)


def test_list_store_lists_saved_configurations_and_skips_foreign_files(make_state, isolated_stores):
    assert list_store() == []
    a, b = make_state(), make_state(components=["Salt"])
    save_to_store(a, "Config A")
    save_to_store(b, "Config B")
    (isolated_stores / "Other").mkdir()
    _write_plain_h5(isolated_stores / "Other" / "config_x.h5")

    assert sorted(list_store()) == sorted(
        [("Config A", compute_hash(a)), ("Config B", compute_hash(b))]
    )


@pytest.mark.parametrize(
    "name, folder", [("My Config", "My_Config"), ("A/B: Config?", "AB_Config"), ("   ", "unnamed")]
)
def test_folder_names_are_filesystem_safe(tmp_path, name, folder):
    assert safe_config_dirname(name) == folder
    assert config_dir(name, store_dir=tmp_path) == tmp_path / folder
    assert (tmp_path / folder).is_dir()


def test_runs_dir_collects_run_files_but_not_configurations(tmp_path):
    folder = config_dir("My Config", store_dir=tmp_path)
    for name in ("run_1.json", "run_1.h5", "config_abc.h5"):
        (folder / name).write_text(name)

    runs = runs_dir("My Config", store_dir=tmp_path)

    assert runs == folder / "runs"
    assert sorted(p.name for p in runs.iterdir()) == ["run_1.h5", "run_1.json"]
    assert [p.name for p in folder.iterdir() if p.is_file()] == ["config_abc.h5"]
