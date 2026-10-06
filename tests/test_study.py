import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from cadetgui.characterization.parameter_store import (
    ParameterSpec,
    ParameterStore,
    Provenance,
)
from cadetgui.characterization.runner import default_optimizer
from cadetgui.characterization.study import Study
from cadetgui.io.experimental_data import Channel, ExperimentalRun

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
LENGTH = "flow_sheet.tubing_pre_column.length"


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


def test_loads_the_example_manifest_with_data(study):
    assert [s.name for s in study.steps] == ["Extra-column volume", "Column packing"]
    assert all(c.run is not None for c in study.comparisons)
    assert study.steps[1].comparisons[0] is study.comparison(study.steps[1].comparisons[0].name)


def test_round_trips_through_json(study, tmp_path):
    posterior = study.initial_store.updated(
        {LENGTH: 0.5}, Provenance(step="Extra-column volume"), specs={LENGTH: ParameterSpec(LENGTH)}
    )
    study.accept("Extra-column volume", posterior)
    for comparison in study.comparisons:
        (tmp_path / comparison.data_file).write_bytes(
            (MANIFEST.parent / comparison.data_file).read_bytes()
        )

    reloaded = Study.load(study.save(tmp_path / "study.json"))

    assert reloaded.to_dict() == study.to_dict()
    assert reloaded.posteriors["Extra-column volume"].value(LENGTH) == 0.5


def test_prior_and_current_store_follow_the_chain(study):
    first = study.initial_store.updated(
        {LENGTH: 0.5}, Provenance(step="Extra-column volume"), specs={LENGTH: ParameterSpec(LENGTH)}
    )
    assert study.prior_for("Column packing") is study.initial_store

    study.accept("Extra-column volume", first)

    assert study.prior_for("Extra-column volume") is study.initial_store
    assert study.prior_for("Column packing") is first
    assert study.current_store is first


def test_listeners_fire_on_changes(study):
    calls = []
    study.add_listener(lambda: calls.append(1))
    study.accept("Extra-column volume", study.initial_store)
    assert len(calls) == 1


def test_removing_a_comparison_a_step_uses_raises(study):
    with pytest.raises(ValueError, match="Extra-column volume"):
        study.remove_comparison("System pulse 1 (UV)")
    study.steps = []
    study.remove_comparison("System pulse 1 (UV)")
    assert "System pulse 1 (UV)" not in [c.name for c in study.comparisons]


def test_excluded_measurements_persist_and_follow_removal(study, tmp_path):
    step = study.steps[0]
    assert step.excluded is None
    study.upsert_step(dataclasses.replace(
        step, comparisons=step.comparisons[:1], excluded=("System pulse 2 (UV)",)
    ))

    reloaded = Study.load(study.save(tmp_path / "study.json"))
    assert reloaded.steps[0].excluded == ("System pulse 2 (UV)",)
    assert reloaded.steps[1].excluded is None

    reloaded.remove_comparison("System pulse 2 (UV)")
    assert reloaded.steps[0].excluded == ()


def test_store_specs_persist_and_conflicts_raise():
    store = ParameterStore().updated(
        {"a.b": {"X": 1.0}}, Provenance(step="s"),
        specs={"a.b": ParameterSpec("a.b", species_indexed=True)},
    )
    raw = json.loads(json.dumps(store.to_dict()))

    assert ParameterStore.from_dict(raw).spec("a.b").species_indexed
    with pytest.raises(ValueError, match="a.b"):
        ParameterStore.from_dict(raw, {"a.b": ParameterSpec("a.b", species_indexed=False)})


def test_replace_comparison_renames_in_place_and_in_steps(study):
    old = study.comparison("System pulse 1 (UV)")
    renamed = dataclasses.replace(old, name="S-A2")
    calls = []
    study.add_listener(lambda: calls.append(1))

    study.replace_comparison("System pulse 1 (UV)", renamed)

    assert study.comparisons[0] is renamed
    assert study.steps[0].comparisons[0] is renamed
    assert study.steps_using("S-A2") == ["Extra-column volume"]
    assert study.steps_using("System pulse 1 (UV)") == []
    assert calls == [1]


def test_replace_comparison_rejects_a_name_clash(study):
    clash = dataclasses.replace(study.comparison("System pulse 1 (UV)"), name="System pulse 2 (UV)")
    with pytest.raises(ValueError, match="already exists"):
        study.replace_comparison("System pulse 1 (UV)", clash)
    with pytest.raises(KeyError):
        study.replace_comparison("nope", dataclasses.replace(clash, name="nope"))


def test_species_gaps_and_explicit_transfer(study):
    from cadetgui.characterization.parameter_store import transfer_species
    from cadetgui.characterization.runner import species_gaps

    dispersion = "flow_sheet.tubing_pre_column.axial_dispersion"
    periphery = study.initial_store.updated(
        {dispersion: {"SystemTracer": 4e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
        specs={dispersion: ParameterSpec(dispersion, species_indexed=True)},
    )
    column_step = study.steps[1]

    gaps = species_gaps(column_step, periphery)
    assert sorted(gaps[dispersion]) == ["LargeTracer", "SmallTracer"]

    transferred = transfer_species(periphery, [dispersion], gaps[dispersion])

    assert dispersion not in species_gaps(column_step, transferred)
    assert transferred.value(dispersion) == {
        "SystemTracer": 4e-7, "SmallTracer": 4e-7, "LargeTracer": 4e-7,
    }
    assert "transferred unchanged" in transferred.entries[dispersion].provenance.note
    assert transferred.entries[dispersion].provenance.probe == "SystemTracer"


def _imported_run() -> ExperimentalRun:
    x = np.linspace(0.0, 5.0, 51)
    return ExperimentalRun(
        label="imported run",
        channels={"UV 1_280": Channel("UV 1_280", x, np.exp(-((x - 2.0) ** 2)))},
        x_basis="volume", x_unit="mL", markers=[(0.5, "Phase Elution")],
    )


def test_save_to_a_new_folder_is_self_contained(study, tmp_path):
    imported = dataclasses.replace(
        study.comparison("System pulse 1 (UV)"), name="S-imported", data_file="imported run.csv",
        run=_imported_run(),
    )
    study.upsert_comparison(imported)
    calls = []
    study.add_listener(lambda: calls.append(1))

    path = study.save(tmp_path / "out" / "study.json")

    assert study.base_dir == path.parent
    assert imported.data_file == "imported run.csv"
    assert calls
    names = sorted(p.name for p in path.parent.iterdir())
    data_file_stems = (
        "system_pulse_1_uv",
        "system_pulse_2_uv",
        "small_tracer_pulse_1_conductivity",
        "small_tracer_pulse_2_conductivity",
        "large_tracer_pulse_1_uv",
        "large_tracer_pulse_2_uv",
    )
    assert names == sorted(
        ["study.json", "imported run.csv"] + [f"{c}.csv" for c in data_file_stems]
    )
    saved_pulse = (path.parent / "system_pulse_1_uv.csv").read_bytes()
    assert saved_pulse == (MANIFEST.parent / "system_pulse_1_uv.csv").read_bytes()

    loaded = Study.load(path)
    run = loaded.comparison("S-imported").run
    np.testing.assert_array_equal(run.channels["UV 1_280"].values,
                                  imported.run.channels["UV 1_280"].values)
    assert run.markers == imported.run.markers
    assert loaded.comparison("S-imported").problems() == imported.problems()


def test_saving_again_to_the_same_folder_writes_nothing_new(study, tmp_path):
    path = study.save(tmp_path / "study.json")
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir() if p.suffix == ".csv"}
    Study.load(path).save(path)
    after = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir() if p.suffix == ".csv"}
    assert after == before


def test_save_never_overwrites_a_different_file(study, tmp_path):
    (tmp_path / "system_pulse_1_uv.csv").write_text("unrelated")
    study.save(tmp_path / "study.json")

    assert (tmp_path / "system_pulse_1_uv.csv").read_text() == "unrelated"
    assert study.comparison("System pulse 1 (UV)").data_file == "system_pulse_1_uv_2.csv"
    assert Study.load(tmp_path / "study.json").comparison("System pulse 1 (UV)").run is not None


def test_step_optimizer_round_trips(study, tmp_path):
    first = study.steps[0]
    assert first.optimizer == default_optimizer(n_variables=first.n_fitted_variables())
    assert first.optimizer == {
        "name": "U-NSGA-III", "knobs": {"pop_size": 16, "n_max_gen": 12}
    }
    second = study.steps[1].optimizer
    study.steps[0].optimizer = default_optimizer("Nelder-Mead", maxiter=50)

    loaded = Study.load(study.save(tmp_path / "study.json"))

    assert loaded.steps[0].optimizer == {"name": "Nelder-Mead", "knobs": {"maxiter": 50}}
    assert loaded.steps[1].optimizer == second


def test_remove_listener(study):
    calls = []

    def listener():
        calls.append(1)

    study.add_listener(listener)
    study.remove_listener(listener)
    study.remove_listener(listener)
    study.notify()
    assert calls == []
