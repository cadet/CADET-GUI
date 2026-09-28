from __future__ import annotations

from cadetgui.parameter_history_store import list_pushes, new_push_id, save_push


def test_save_push_round_trips_provenance(tmp_path):
    push_id = new_push_id()
    saved = save_push(
        push_id, "bed", {"bed_porosity": 0.4}, dataset_labels=["d0", "d1"],
        optimizer_name="Nelder-Mead", objective=1.5, config_hash="abc", config_name="Cfg",
        store_dir=tmp_path,
    )

    (loaded,) = list_pushes(store_dir=tmp_path)

    assert loaded == saved
    assert loaded.push_id == push_id
    assert loaded.values == {"bed_porosity": 0.4}
    assert loaded.dataset_labels == ["d0", "d1"]
    assert (loaded.optimizer_name, loaded.objective) == ("Nelder-Mead", 1.5)
    assert (loaded.config_hash, loaded.config_name) == ("abc", "Cfg")


def test_list_pushes_is_newest_first(tmp_path):
    first, second = new_push_id(), new_push_id()
    save_push(first, "periphery", {"a": 1.0}, store_dir=tmp_path)
    save_push(second, "bed", {"b": 2.0}, store_dir=tmp_path)

    assert [p.push_id for p in list_pushes(store_dir=tmp_path)] == [second, first]


def test_save_push_copies_its_inputs(tmp_path):
    values, labels = {"a": 1.0}, ["d0"]
    saved = save_push(new_push_id(), "bed", values, dataset_labels=labels, store_dir=tmp_path)

    values["a"] = 2.0
    labels.append("d1")

    assert saved.values == {"a": 1.0}
    assert saved.dataset_labels == ["d0"]
