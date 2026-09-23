from __future__ import annotations

import cadetgui.parameter_history_store as parameter_history_store
from cadetgui.widgets.composite import ParameterHistoryWidget


def test_record_appends_and_selects_newest():
    h = ParameterHistoryWidget()
    h.record("periphery", {"tubing_pre_injection_length": 2.5})
    h.record("bed", {"bed_porosity": 0.4})

    assert [p.stage for p in h.pushes] == ["periphery", "bed"]
    assert h.selected.stage == "bed"
    assert h.selected.values == {"bed_porosity": 0.4}


def test_record_carries_provenance():
    h = ParameterHistoryWidget()
    push = h.record(
        "bed", {"bed_porosity": 0.4, "axial_dispersion": 1e-7},
        dataset_labels=["d0", "d1"], optimizer_name="U-NSGA-III", objective=1.23,
        config_name="Cfg", config_hash="abc123",
    )

    assert push.dataset_labels == ["d0", "d1"]
    assert push.optimizer_name == "U-NSGA-III"
    assert push.objective == 1.23
    assert push.config_name == "Cfg"
    assert push.config_hash == "abc123"


def test_picking_a_push_notifies_listeners_and_renders_details():
    h = ParameterHistoryWidget()
    h.record("periphery", {"tubing_pre_injection_length": 2.5})
    h.record("bed", {"bed_porosity": 0.4})

    seen = []
    h.add_listener(seen.append)

    h._picker.selected_index = 0
    assert len(seen) == 1
    assert seen[0].stage == "periphery"
    assert "tubing_pre_injection_length" in h._details.value


def test_picking_the_same_push_again_does_not_renotify():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})

    seen = []
    h.add_listener(seen.append)
    h._picker.selected_index = 0  # already selected
    assert seen == []


def test_reapply_only_fires_on_explicit_button_click_not_on_pick():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})
    h.record("bed", {"bed_porosity": 0.42})

    reapplied = []
    h.add_reapply_listener(reapplied.append)
    h._picker.selected_index = 0  # merely viewing -- must not trigger reapply

    assert reapplied == []

    h._on_reapply_click(None)
    assert len(reapplied) == 1
    assert reapplied[0].values == {"bed_porosity": 0.4}


def test_reapply_button_hidden_when_nothing_is_selected():
    h = ParameterHistoryWidget()
    assert h._btn_reapply.layout.display == "none"


def test_clear_empties_history():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})
    h.clear()

    assert h.pushes == []
    assert h.selected is None
    assert h._picker.option_labels == []


def test_describe_format_includes_index_stage_and_parameter_names():
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4, "axial_dispersion": 1e-7})

    label = h._picker.option_labels[0]
    assert label.startswith("#1")
    assert "bed" in label
    assert "bed_porosity" in label
    assert "axial_dispersion" in label


def test_default_store_dir_is_none_and_nothing_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        parameter_history_store, "default_parameter_history_store_dir", lambda: tmp_path
    )
    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})

    assert h.store_dir is None
    assert parameter_history_store.list_pushes(store_dir=tmp_path) == []


def test_record_persists_metadata_when_store_dir_is_set(tmp_path):
    h = ParameterHistoryWidget(store_dir=tmp_path)
    push = h.record(
        "bed", {"bed_porosity": 0.4}, dataset_labels=["d0"], config_name="Cfg", config_hash="abc",
    )

    persisted = parameter_history_store.list_pushes(store_dir=tmp_path)
    assert len(persisted) == 1
    assert persisted[0].push_id == push.push_id
    assert persisted[0].stage == "bed"
    assert persisted[0].values == {"bed_porosity": 0.4}
    assert persisted[0].config_name == "Cfg"
    assert persisted[0].config_hash == "abc"


def test_construction_loads_existing_pushes_from_store_dir(tmp_path):
    parameter_history_store.save_push(
        parameter_history_store.new_push_id(), "bed", {"bed_porosity": 0.4}, store_dir=tmp_path,
    )

    h = ParameterHistoryWidget(store_dir=tmp_path)

    assert [p.stage for p in h.pushes] == ["bed"]
    assert h.selected.values == {"bed_porosity": 0.4}


def test_setting_store_dir_via_the_ui_field_loads_that_folders_history(tmp_path):
    parameter_history_store.save_push(
        parameter_history_store.new_push_id(), "capacity", {"capacity": 100.0}, store_dir=tmp_path,
    )

    h = ParameterHistoryWidget()
    h.record("bed", {"bed_porosity": 0.4})
    h._store_dir_field.value = str(tmp_path)
    h._on_set_store_dir(None)

    assert [p.stage for p in h.pushes] == ["capacity"]
    assert h.store_dir == tmp_path.resolve()


def test_setting_store_dir_via_the_ui_field_fires_the_manual_change_callback(tmp_path):
    seen = []
    h = ParameterHistoryWidget(on_manual_store_dir_change=seen.append)

    h._store_dir_field.value = str(tmp_path)
    h._on_set_store_dir(None)

    assert seen == [tmp_path.resolve()]
