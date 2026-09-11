from __future__ import annotations

import warnings

import pytest
from cadet import H5
from cadetgui.configuration_store import (
    ConfigurationState,
    compute_hash,
    load_from_store,
    load_h5,
    save_h5,
    save_to_store,
)

warnings.filterwarnings("ignore", category=UserWarning)


def _sample_state(**overrides) -> ConfigurationState:
    defaults = dict(
        components=["Salt", "Protein"],
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="Linear",
        template_key="Batch Elution",
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

    assert path.name == f"{compute_hash(state)}.h5"
    name, loaded = load_from_store(compute_hash(state), store_dir=tmp_path)
    assert name == "My Config"
    assert loaded == state


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
