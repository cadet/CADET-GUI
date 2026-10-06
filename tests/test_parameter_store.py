from __future__ import annotations

import pytest
from cadetgui.characterization.parameter_store import (
    ChainError,
    Entry,
    ParameterSpec,
    ParameterStore,
    Provenance,
    Step,
    apply_store,
    check_chain,
    missing_requirements,
    read_process,
    spec_for,
    species_index,
)
from CADETProcess.instruments import LCFlowSheet, LCProcess
from CADETProcess.processModel import ComponentSystem, GeneralRateModel

BED_POROSITY = "flow_sheet.column.bed_porosity"
FILM_DIFFUSION = "flow_sheet.column.film_diffusion"
DETECTOR_LENGTH = "flow_sheet.tubing_detectors.length"

_SPECS = {
    BED_POROSITY: ParameterSpec(BED_POROSITY),
    FILM_DIFFUSION: ParameterSpec(FILM_DIFFUSION, species_indexed=True),
    DETECTOR_LENGTH: ParameterSpec(DETECTOR_LENGTH),
}


@pytest.fixture
def component_system():
    return ComponentSystem(["A", "B"])


@pytest.fixture
def process(component_system):
    flow_sheet = LCFlowSheet(component_system, ColumnModel=GeneralRateModel)
    return LCProcess("demo", flow_sheet)


@pytest.fixture
def bypassed_process(component_system):
    flow_sheet = LCFlowSheet(
        component_system, ColumnModel=GeneralRateModel, bypass_units=["tubing_detectors"]
    )
    return LCProcess("demo", flow_sheet)


def _seeded_store() -> ParameterStore:
    return ParameterStore(specs=_SPECS).updated(
        {BED_POROSITY: 0.4, FILM_DIFFUSION: {"A": 1e-5, "B": 2e-5}, DETECTOR_LENGTH: 0.5},
        Provenance(step="seed"),
    )


def test_species_index_resolves_against_a_real_component_system(component_system):
    assert species_index("A", component_system) == 0
    assert species_index("B", component_system) == 1


def test_species_index_rejects_an_unknown_species(component_system):
    with pytest.raises(KeyError):
        species_index("C", component_system)


def test_value_round_trips_scalar_and_species_indexed():
    store = _seeded_store()
    assert store.value(BED_POROSITY) == 0.4
    assert store.value(FILM_DIFFUSION) == {"A": 1e-5, "B": 2e-5}
    assert store.value(FILM_DIFFUSION, species="B") == 2e-5


def test_value_rejects_species_for_a_scalar_parameter():
    store = _seeded_store()
    with pytest.raises(ValueError):
        store.value(BED_POROSITY, species="A")


def test_updated_returns_a_new_store_and_leaves_the_original_untouched():
    base = ParameterStore(specs=_SPECS)
    updated = base.updated({BED_POROSITY: 0.4}, Provenance(step="seed"))

    assert BED_POROSITY not in base
    assert BED_POROSITY in updated
    assert updated.step == "seed"
    assert updated.prior is None


def test_updated_merges_species_indexed_values_instead_of_overwriting():
    store = ParameterStore(specs=_SPECS).updated(
        {FILM_DIFFUSION: {"A": 1e-5}}, Provenance(step="one")
    )
    store = store.updated({FILM_DIFFUSION: {"B": 2e-5}}, Provenance(step="two"))

    assert store.value(FILM_DIFFUSION) == {"A": 1e-5, "B": 2e-5}
    assert store.step == "two"
    assert store.prior == "one"


def test_updated_rejects_undeclared_paths():
    with pytest.raises(KeyError):
        ParameterStore().updated({BED_POROSITY: 0.4}, Provenance(step="seed"))


def test_updated_accepts_new_specs_declared_inline():
    store = ParameterStore().updated(
        {BED_POROSITY: 0.4}, Provenance(step="seed"), specs={BED_POROSITY: _SPECS[BED_POROSITY]}
    )
    assert store.value(BED_POROSITY) == 0.4
    assert BED_POROSITY in store.specs


def test_updated_rejects_a_mapping_for_a_non_species_indexed_parameter():
    with pytest.raises(TypeError):
        ParameterStore(specs=_SPECS).updated({BED_POROSITY: {"A": 0.4}}, Provenance(step="seed"))


def test_updated_rejects_a_scalar_for_a_species_indexed_parameter():
    with pytest.raises(TypeError):
        ParameterStore(specs=_SPECS).updated({FILM_DIFFUSION: 1e-5}, Provenance(step="seed"))


def test_to_cadet_orders_species_by_index(component_system):
    store = _seeded_store()
    assert store.to_cadet(FILM_DIFFUSION, component_system) == [1e-5, 2e-5]
    assert store.to_cadet(BED_POROSITY, component_system) == 0.4


def test_to_cadet_raises_for_a_species_missing_from_the_store(component_system):
    store = ParameterStore(specs=_SPECS).updated(
        {FILM_DIFFUSION: {"A": 1e-5}}, Provenance(step="seed")
    )
    with pytest.raises(KeyError):
        store.to_cadet(FILM_DIFFUSION, component_system)


def test_from_cadet_is_the_inverse_of_to_cadet(component_system):
    store = _seeded_store()
    cadet_value = store.to_cadet(FILM_DIFFUSION, component_system)
    assert store.from_cadet(FILM_DIFFUSION, cadet_value, component_system) == {
        "A": 1e-5,
        "B": 2e-5,
    }


def test_json_round_trip(tmp_path):
    store = _seeded_store()
    path = store.save(tmp_path / "store.json")

    loaded = ParameterStore.load(path, specs=_SPECS)
    assert loaded.entries == store.entries
    assert loaded.step == store.step
    assert loaded.prior == store.prior


def test_from_dict_is_the_inverse_of_to_dict():
    store = _seeded_store()
    rebuilt = ParameterStore.from_dict(store.to_dict(), specs=_SPECS)
    assert rebuilt.entries == store.entries


def test_to_dict_omits_unset_provenance_fields():
    store = ParameterStore(specs=_SPECS).updated({BED_POROSITY: 0.4}, Provenance(step="seed"))
    assert store.to_dict()["entries"][BED_POROSITY]["provenance"] == {"step": "seed"}


def test_spec_for_infers_species_indexed_from_the_descriptor(process):
    assert spec_for(process, FILM_DIFFUSION) == ParameterSpec(FILM_DIFFUSION, species_indexed=True)
    assert spec_for(process, BED_POROSITY) == ParameterSpec(BED_POROSITY, species_indexed=False)


def test_spec_for_raises_for_an_absent_path(process):
    with pytest.raises(KeyError):
        spec_for(process, "flow_sheet.column.not_a_parameter")


def test_apply_store_sets_parameters_the_process_has(process):
    store = _seeded_store()
    applied = apply_store(process, store)

    assert sorted(applied) == sorted([BED_POROSITY, FILM_DIFFUSION, DETECTOR_LENGTH])
    assert process.flow_sheet.column.bed_porosity == 0.4
    assert process.flow_sheet.column.film_diffusion == [1e-5, 2e-5]
    assert process.flow_sheet.tubing_detectors.length == 0.5


def test_apply_store_skips_paths_for_a_bypassed_unit(bypassed_process):
    store = _seeded_store()
    applied = apply_store(bypassed_process, store)

    assert DETECTOR_LENGTH not in applied
    assert sorted(applied) == [BED_POROSITY, FILM_DIFFUSION]


def test_read_process_mirrors_apply_store(process):
    store = _seeded_store()
    apply_store(process, store)

    values = read_process(process, [BED_POROSITY, FILM_DIFFUSION], store)
    assert values == {BED_POROSITY: 0.4, FILM_DIFFUSION: {"A": 1e-5, "B": 2e-5}}


def test_read_process_raises_for_a_path_the_process_does_not_have(bypassed_process):
    store = _seeded_store()
    with pytest.raises(KeyError):
        read_process(bypassed_process, [DETECTOR_LENGTH], store)


def test_missing_requirements_is_non_raising():
    step = Step(name="fit", requires=(BED_POROSITY, "nope.path"), provides=())
    assert missing_requirements(step, ParameterStore()) == [BED_POROSITY, "nope.path"]

    store = ParameterStore(specs=_SPECS).updated({BED_POROSITY: 0.4}, Provenance(step="seed"))
    assert missing_requirements(step, store) == ["nope.path"]


def test_check_chain_accepts_a_valid_ordering():
    initial = ParameterStore(specs=_SPECS)
    steps = [
        Step(name="tubing", requires=(), provides=(DETECTOR_LENGTH,)),
        Step(name="column", requires=(DETECTOR_LENGTH,), provides=(BED_POROSITY,)),
    ]
    check_chain(steps, initial)


def test_check_chain_rejects_a_step_that_requires_an_unprovided_path():
    initial = ParameterStore(specs=_SPECS)
    steps = [Step(name="column", requires=(DETECTOR_LENGTH,), provides=(BED_POROSITY,))]
    with pytest.raises(ChainError):
        check_chain(steps, initial)


def test_check_chain_rejects_a_duplicate_step_name():
    initial = ParameterStore(specs=_SPECS)
    steps = [
        Step(name="column", requires=(), provides=(BED_POROSITY,)),
        Step(name="column", requires=(), provides=(DETECTOR_LENGTH,)),
    ]
    with pytest.raises(ChainError):
        check_chain(steps, initial)


def test_check_chain_rejects_an_undeclared_path():
    initial = ParameterStore()
    steps = [Step(name="column", requires=(), provides=(BED_POROSITY,))]
    with pytest.raises(ChainError):
        check_chain(steps, initial)


def test_entry_is_a_plain_value_provenance_pair():
    entry = Entry(value=0.4, provenance=Provenance(step="seed"))
    assert entry.value == 0.4
    assert entry.provenance.step == "seed"
