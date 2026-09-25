from __future__ import annotations

import warnings

import pytest
from cadet import H5
from cadetgui.configuration_store import (
    ConfigurationState,
    InstrumentState,
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

warnings.filterwarnings("ignore", category=UserWarning)


def _sample_instrument(**overrides) -> InstrumentState:
    defaults = dict(
        include_sample_loop=True,
        sample_loop_volume=50e-9,
        sample_loop_diameter_auto=True,
        sample_loop_diameter=0.75e-3,
        bypass_units=[],
    )
    defaults.update(overrides)
    return InstrumentState(**defaults)


def _sample_state(
    *, instrument: InstrumentState | None = "__default__", **overrides
) -> ConfigurationState:
    defaults = dict(
        components=["Salt", "Protein"],
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="Linear",
        template_key="Load–Wash–Elute (LWE)",
        instrument=_sample_instrument() if instrument == "__default__" else instrument,
        multiplex_state={"axial_dispersion": False},
        show_optional_column=False,
        show_optional_binding=True,
        column_values={"length": 0.5, "diameter": 0.024},
        binding_values={"is_kinetic": True, "adsorption_rate": [0.0, 1.5]},
        model_values={"flow_rate": 1e-6, "cycle_time": 6000.0},
    )
    defaults.update(overrides)
    return ConfigurationState(**defaults)


def test_hash_is_deterministic_regardless_of_construction_order():
    state_a = _sample_state()
    state_b = ConfigurationState(**state_a.__dict__)
    assert compute_hash(state_a) == compute_hash(state_b)


def test_hash_changes_when_a_value_changes():
    state_a = _sample_state()
    state_b = _sample_state(column_values={"length": 0.6, "diameter": 0.024})
    assert compute_hash(state_a) != compute_hash(state_b)


def test_save_and_load_h5_round_trips_the_full_state(tmp_path):
    state = _sample_state()
    path = tmp_path / "config.h5"

    save_h5(state, "My Config", path)
    name, loaded = load_h5(path)

    assert name == "My Config"
    assert loaded == state
    assert compute_hash(loaded) == compute_hash(state)


def test_load_h5_ignores_a_legacy_use_lc_system_key(tmp_path):
    state = _sample_state()
    path = tmp_path / "legacy.h5"
    save_h5(state, "Legacy", path)

    h5 = H5()
    h5.filename = str(path)
    h5.load_from_file()
    h5.root.cadetgui.state.instrument.use_lc_system = False
    h5.save()

    name, loaded = load_h5(path)

    assert name == "Legacy"
    assert loaded == state
    assert compute_hash(loaded) == compute_hash(state)


def test_save_and_load_h5_round_trips_a_standalone_state_with_no_instrument(tmp_path):
    # HDF5 has no NoneType -- instrument=None must round-trip cleanly, not
    # crash on save or come back as some other falsy value on load.
    state = _sample_state(instrument=None)
    path = tmp_path / "standalone.h5"

    save_h5(state, "Standalone Config", path)
    name, loaded = load_h5(path)

    assert name == "Standalone Config"
    assert loaded == state
    assert loaded.instrument is None


def test_save_and_load_h5_round_trips_nested_unit_values(tmp_path):
    # unit_values is a dict-of-dicts (per mixer/tubing unit) -- make sure the
    # H5 round trip doesn't flatten or mangle the nesting.
    state = _sample_state(
        instrument=_sample_instrument(
            unit_values={
                "mixer": {"init_liquid_volume": 2.5e-5},
                "tubing_pre_column": {"length": 0.33, "diameter": 0.001, "axial_dispersion": 2e-8},
            }
        )
    )
    path = tmp_path / "unit_values.h5"

    save_h5(state, "Nested Config", path)
    _, loaded = load_h5(path)

    assert loaded.instrument.unit_values == state.instrument.unit_values
    assert loaded == state


def test_load_h5_rejects_a_file_with_no_cadetgui_group(tmp_path):
    path = tmp_path / "plain.h5"
    h5 = H5()
    h5.root.some_other_data = 1
    h5.filename = str(path)
    h5.save()

    with pytest.raises(ValueError, match="cadetgui"):
        load_h5(path)


def test_save_to_store_and_load_from_store_round_trip(tmp_path):
    state = _sample_state()
    path = save_to_store(state, "My Config", store_dir=tmp_path)

    assert path.name == f"config_{compute_hash(state)}.h5"
    assert path.parent == tmp_path / "My_Config"
    name, loaded = load_from_store(compute_hash(state), store_dir=tmp_path)
    assert name == "My Config"
    assert loaded == state


def test_safe_config_dirname_replaces_whitespace_and_drops_unsafe_characters():
    assert safe_config_dirname("My Config") == "My_Config"
    assert safe_config_dirname("A/B: Config?") == "AB_Config"
    assert safe_config_dirname("   ") == "unnamed"


def test_config_dir_creates_a_subfolder_named_after_the_configuration(tmp_path):
    path = config_dir("My Config", store_dir=tmp_path)

    assert path == tmp_path / "My_Config"
    assert path.is_dir()


def test_runs_dir_is_a_runs_subfolder_of_the_configuration_folder(tmp_path):
    path = runs_dir("My Config", store_dir=tmp_path)

    assert path == tmp_path / "My_Config" / "runs"
    assert path.is_dir()


def test_runs_dir_moves_runs_left_in_the_configuration_folder_but_not_its_configs(tmp_path):
    folder = config_dir("My Config", store_dir=tmp_path)
    for name in ("run_1.json", "run_1.h5", "config_abc.h5"):
        (folder / name).write_text(name)

    path = runs_dir("My Config", store_dir=tmp_path)

    assert sorted(p.name for p in path.iterdir()) == ["run_1.h5", "run_1.json"]
    assert [p.name for p in folder.iterdir() if p.is_file()] == ["config_abc.h5"]
    assert (path / "run_1.json").read_text() == "run_1.json"


def test_save_to_store_reuses_the_existing_folder_for_identical_content_under_a_new_name(
    tmp_path,
):
    # Content hash stays the true identity -- renaming must not change it, and
    # two identical configurations under different names still collide to one
    # file (ARCHITECTURE.md), even with the per-name subfolder layout: the
    # folder simply keeps whichever name first saved that content.
    state = _sample_state()
    path_a = save_to_store(state, "Name A", store_dir=tmp_path)
    path_b = save_to_store(state, "Name B", store_dir=tmp_path)

    assert path_a == path_b
    assert path_a.parent == tmp_path / "Name_A"
    assert not (tmp_path / "Name_B").exists()


def test_load_from_store_raises_a_clear_error_for_an_unknown_hash(tmp_path):
    with pytest.raises(FileNotFoundError, match="deadbeef"):
        load_from_store("deadbeef", store_dir=tmp_path)


def test_save_to_store_is_idempotent_for_identical_content(tmp_path):
    state = _sample_state()
    path_a = save_to_store(state, "Name A", store_dir=tmp_path)
    path_b = save_to_store(state, "Name B", store_dir=tmp_path)

    assert path_a == path_b  # same content -> same hash -> same file
    name, loaded = load_from_store(compute_hash(state), store_dir=tmp_path)
    assert name == "Name B"  # last write wins for the metadata, content unchanged
    assert loaded == state


def test_list_store_is_empty_for_a_fresh_store_dir(tmp_path):
    assert list_store(store_dir=tmp_path) == []


def test_list_store_lists_every_saved_configuration_as_name_hash_pairs(tmp_path):
    state_a = _sample_state()
    state_b = _sample_state(column_values={"length": 0.6, "diameter": 0.024})
    save_to_store(state_a, "Config A", store_dir=tmp_path)
    save_to_store(state_b, "Config B", store_dir=tmp_path)

    entries = list_store(store_dir=tmp_path)

    assert {name for name, _ in entries} == {"Config A", "Config B"}
    assert {hash_ for _, hash_ in entries} == {compute_hash(state_a), compute_hash(state_b)}


def test_list_store_skips_a_non_cadetgui_h5_file(tmp_path):
    state = _sample_state()
    save_to_store(state, "Config A", store_dir=tmp_path)

    h5 = H5()
    h5.root.some_other_data = 1
    h5.filename = str(tmp_path / "not_a_config.h5")
    h5.save()

    entries = list_store(store_dir=tmp_path)

    assert [name for name, _ in entries] == ["Config A"]
