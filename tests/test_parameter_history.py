from __future__ import annotations

import dataclasses

import cadetgui.parameter_history_store as parameter_history_store
from cadetgui.widgets.composite import ParameterHistoryWidget


def test_record_appends_and_selects_newest():
    h = ParameterHistoryWidget()
    h.record("periphery", {"tubing_pre_injection_length": 2.5})
    h.record("bed", {"bed_porosity": 0.4})

    assert [p.stage for p in h.pushes] == ["periphery", "bed"]
    assert h.selected.stage == "bed"
    assert h.selected.values == {"bed_porosity": 0.4}


def test_picking_a_push_renders_its_provenance_and_offers_reapply():
    h = ParameterHistoryWidget()
    assert h._btn_reapply.layout.display == "none"
    h.record("periphery", {"tubing_pre_injection_length": 2.5})
    h.record(
        "bed", {"bed_porosity": 0.4}, dataset_labels=["d0", "d1"],
        optimizer_name="U-NSGA-III", objective=1.23,
    )

    h._picker.selected_index = 0
    assert "tubing_pre_injection_length" in h._details.value
    assert "U-NSGA-III" not in h._details.value

    h._picker.selected_index = 1
    for text in ("bed_porosity", "d0, d1", "U-NSGA-III", "1.23"):
        assert text in h._details.value
    assert h._btn_reapply.layout.display == ""


def test_reapply_only_fires_on_explicit_button_click_not_on_pick():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})
    h.record("bed", {"bed_porosity": 0.42})

    reapplied = []
    h.add_reapply_listener(reapplied.append)
    h._picker.selected_index = 0  # merely viewing -- must not trigger reapply

    assert reapplied == []

    h._on_reapply_click(None)
    assert [p.values for p in reapplied] == [{"bed_porosity": 0.4}]


def test_picker_labels_and_table_rows_list_index_stage_and_sorted_parameter_names():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4, "axial_dispersion": 1e-7})

    label = h._picker.option_labels[0]
    assert label.startswith("#1") and " bed " in label
    assert label.endswith("axial_dispersion, bed_porosity")
    (row,) = h._picker.rows
    assert [cell["text"] for cell in row][::2] == ["1", "bed"]
    assert row[3]["text"] == "axial_dispersion, bed_porosity"


def test_nothing_is_persisted_without_a_store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        parameter_history_store, "default_parameter_history_store_dir", lambda: tmp_path
    )
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})

    assert h.store_dir is None
    assert parameter_history_store.list_pushes(store_dir=tmp_path) == []


def test_record_persists_the_push_with_its_provenance(tmp_path):
    h = ParameterHistoryWidget(store_dir=tmp_path)
    push = h.record(
        "bed", {"bed_porosity": 0.4}, dataset_labels=["d0"], optimizer_name="Nelder-Mead",
        objective=0.5, config_name="Cfg", config_hash="abc",
    )

    (persisted,) = parameter_history_store.list_pushes(store_dir=tmp_path)
    assert persisted == dataclasses.replace(push, timestamp=persisted.timestamp)


def test_setting_store_dir_replaces_the_history_with_that_folders_pushes(tmp_path):
    parameter_history_store.save_push(
        parameter_history_store.new_push_id(), "capacity", {"capacity": 100.0}, store_dir=tmp_path,
    )
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})

    h.store_dir = tmp_path

    assert h.store_dir == tmp_path.resolve()
    assert [p.stage for p in h.pushes] == ["capacity"]
    assert h.selected.values == {"capacity": 100.0}

    h.store_dir = None

    assert h.pushes == []
    assert h.selected is None
