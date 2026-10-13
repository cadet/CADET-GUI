"""ParameterStore: values with provenance, species, JSON, process apply/read and chain checks."""
from __future__ import annotations

import json

import pytest
from cadetgui.characterization.parameter_store import (
    ChainError,
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

POROSITY = "flow_sheet.column.bed_porosity"
FILM = "flow_sheet.column.film_diffusion"
DETECTOR_LENGTH = "flow_sheet.tubing_detectors.length"
SPECS = {
    POROSITY: ParameterSpec(POROSITY),
    FILM: ParameterSpec(FILM, species_indexed=True),
    DETECTOR_LENGTH: ParameterSpec(DETECTOR_LENGTH),
}


@pytest.fixture
def component_system():
    return ComponentSystem(["A", "B"])


def lc_process(component_system, bypass=()):
    flow_sheet = LCFlowSheet(
        component_system, ColumnModel=GeneralRateModel, bypass_units=list(bypass)
    )
    return LCProcess("demo", flow_sheet)


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore(specs=SPECS).updated(
        {POROSITY: 0.4, FILM: {"A": 1e-5, "B": 2e-5}, DETECTOR_LENGTH: 0.5},
        Provenance(step="seed"),
    )


def test_values_scalar_and_per_species(store):
    assert store.value(POROSITY) == 0.4
    assert store.value(FILM) == {"A": 1e-5, "B": 2e-5}
    assert store.value(FILM, species="B") == 2e-5
    with pytest.raises(ValueError):
        store.value(POROSITY, species="A")


def test_updated_returns_a_new_store_and_merges_species():
    base = ParameterStore(specs=SPECS)
    one = base.updated({FILM: {"A": 1e-5}}, Provenance(step="one"))
    two = one.updated({FILM: {"B": 2e-5}}, Provenance(step="two"))

    assert FILM not in base
    assert one.step == "one" and one.prior is None
    assert two.value(FILM) == {"A": 1e-5, "B": 2e-5}
    assert two.step == "two" and two.prior == "one"
    inline = ParameterStore().updated(
        {POROSITY: 0.4}, Provenance(step="s"), specs={POROSITY: SPECS[POROSITY]}
    )
    assert inline.value(POROSITY) == 0.4


@pytest.mark.parametrize("specs, values, error", [
    ({}, {POROSITY: 0.4}, KeyError),
    (SPECS, {POROSITY: {"A": 0.4}}, TypeError),
    (SPECS, {FILM: 1e-5}, TypeError),
])
def test_updated_rejects_values_that_do_not_fit_the_specs(specs, values, error):
    with pytest.raises(error):
        ParameterStore(specs=specs).updated(values, Provenance(step="seed"))


def test_species_map_to_cadet_by_component_index(store, component_system):
    assert species_index("B", component_system) == 1
    with pytest.raises(KeyError):
        species_index("C", component_system)
    cadet = store.to_cadet(FILM, component_system)
    assert cadet == [1e-5, 2e-5]
    assert store.from_cadet(FILM, cadet, component_system) == {"A": 1e-5, "B": 2e-5}
    assert store.to_cadet(POROSITY, component_system) == 0.4
    partial = ParameterStore(specs=SPECS).updated({FILM: {"A": 1e-5}}, Provenance(step="s"))
    with pytest.raises(KeyError):
        partial.to_cadet(FILM, component_system)


def test_json_round_trip(store, tmp_path):
    loaded = ParameterStore.load(store.save(tmp_path / "store.json"), specs=SPECS)
    assert (loaded.entries, loaded.step, loaded.prior) == (store.entries, store.step, store.prior)

    raw = json.loads(json.dumps(store.to_dict()))
    assert raw["entries"][POROSITY]["provenance"] == {"step": "seed"}
    assert ParameterStore.from_dict(raw).spec(FILM).species_indexed
    with pytest.raises(ValueError, match=FILM):
        ParameterStore.from_dict(raw, {FILM: ParameterSpec(FILM, species_indexed=False)})


def test_spec_for_reads_species_indexing_from_the_process(component_system):
    process = lc_process(component_system)
    assert spec_for(process, FILM) == ParameterSpec(FILM, species_indexed=True)
    assert spec_for(process, POROSITY) == ParameterSpec(POROSITY, species_indexed=False)
    with pytest.raises(KeyError):
        spec_for(process, "flow_sheet.column.not_a_parameter")


@pytest.mark.parametrize("bypass, applied", [
    ((), [POROSITY, FILM, DETECTOR_LENGTH]),
    (("tubing_detectors",), [POROSITY, FILM]),
])
def test_apply_store_sets_what_the_process_has_and_read_process_mirrors_it(
    store, component_system, bypass, applied
):
    process = lc_process(component_system, bypass)
    assert sorted(apply_store(process, store)) == sorted(applied)
    assert process.flow_sheet.column.film_diffusion == [1e-5, 2e-5]
    assert read_process(process, [POROSITY, FILM], store) == {
        POROSITY: 0.4, FILM: {"A": 1e-5, "B": 2e-5},
    }
    if bypass:
        with pytest.raises(KeyError):
            read_process(process, [DETECTOR_LENGTH], store)
    else:
        assert process.flow_sheet.tubing_detectors.length == 0.5


def test_missing_requirements_is_non_raising():
    step = Step(name="fit", requires=(POROSITY, "nope.path"), provides=())
    assert missing_requirements(step, ParameterStore()) == [POROSITY, "nope.path"]
    store = ParameterStore(specs=SPECS).updated({POROSITY: 0.4}, Provenance(step="seed"))
    assert missing_requirements(step, store) == ["nope.path"]


def test_check_chain_accepts_a_valid_ordering():
    check_chain([
        Step(name="tubing", requires=(), provides=(DETECTOR_LENGTH,)),
        Step(name="column", requires=(DETECTOR_LENGTH,), provides=(POROSITY,)),
    ], ParameterStore(specs=SPECS))


@pytest.mark.parametrize("specs, steps", [
    (SPECS, [Step(name="column", requires=(DETECTOR_LENGTH,), provides=(POROSITY,))]),
    (SPECS, [Step(name="c", requires=(), provides=(POROSITY,)),
             Step(name="c", requires=(), provides=(DETECTOR_LENGTH,))]),
    ({}, [Step(name="column", requires=(), provides=(POROSITY,))]),
], ids=["unprovided requirement", "duplicate name", "undeclared path"])
def test_check_chain_rejects(specs, steps):
    with pytest.raises(ChainError):
        check_chain(steps, ParameterStore(specs=specs))
