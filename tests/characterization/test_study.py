"""Study: measurements, steps, components, the accept chain and saving."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from cadetgui.characterization.guide import EXPERIMENT_TYPES, SALT, measurement_from_run
from cadetgui.characterization.parameter_store import Provenance, transfer_species
from cadetgui.characterization.runner import default_optimizer, species_gaps
from cadetgui.characterization.study import Study, StudyComponent, derive_components
from cadetgui.io.experimental_data import Channel, ExperimentalRun

from characterization.synthetic import DATA_DIR, DISPERSION, LENGTH, MANIFEST

EXAMPLE_COMPONENTS = [
    StudyComponent("SystemTracer", "system tracer"),
    StudyComponent("SmallTracer", "small tracer"),
    StudyComponent("LargeTracer", "large tracer"),
]


def gradient(study: Study, name: str = "Gradient 1", component: str = "IgG"):
    source = study.comparison("Large tracer pulse 1 (UV)")
    return measurement_from_run(
        name, source.run, "UV 1_280", EXPERIMENT_TYPES["linear_gradient_elution"],
        source.recipe, component=component,
    )


@pytest.fixture
def calls(study):
    seen = []
    study.add_listener(lambda: seen.append(1))
    return seen


def test_example_loads_with_data_and_shared_comparisons(study):
    assert [s.name for s in study.steps] == ["Extra-column volume", "Column packing"]
    assert all(c.run is not None for c in study.comparisons)
    assert study.steps[1].comparisons[0] is study.comparison(study.steps[1].comparisons[0].name)
    assert study.components == EXAMPLE_COMPONENTS


def test_json_round_trip_keeps_posteriors_components_exclusions_and_optimizer(
    study, periphery_posterior, tmp_path
):
    study.accept("Extra-column volume", periphery_posterior)
    study.add_component("IgG", "protein")
    step = study.steps[0]
    study.upsert_step(dataclasses.replace(
        step, comparisons=step.comparisons[:1], excluded=("System pulse 2 (UV)",),
        optimizer=default_optimizer("Nelder-Mead", maxiter=50),
    ))

    reloaded = Study.load(study.save(tmp_path / "study.json"))

    assert reloaded.to_dict() == study.to_dict()
    assert reloaded.posteriors["Extra-column volume"].value(LENGTH) == 0.42
    assert reloaded.components[-1] == StudyComponent("IgG", "protein")
    assert reloaded.steps[0].excluded == ("System pulse 2 (UV)",)
    assert reloaded.steps[1].excluded is None
    assert reloaded.steps[0].optimizer == {"name": "Nelder-Mead", "knobs": {"maxiter": 50}}
    assert reloaded.steps[1].optimizer == study.steps[1].optimizer


def test_prior_and_current_store_follow_the_accept_chain(study, periphery_posterior, calls):
    assert study.prior_for("Column packing") is study.initial_store

    study.accept("Extra-column volume", periphery_posterior)

    assert calls == [1]
    assert study.prior_for("Extra-column volume") is study.initial_store
    assert study.prior_for("Column packing") is periphery_posterior
    assert study.current_store is periphery_posterior


def test_remove_listener():
    study, calls = Study(), []

    def listener():
        calls.append(1)

    study.add_listener(listener)
    study.remove_listener(listener)
    study.remove_listener(listener)
    study.notify()
    assert calls == []


def test_removing_a_comparison_a_step_uses_raises_and_exclusions_follow(study):
    with pytest.raises(ValueError, match="Extra-column volume"):
        study.remove_comparison("System pulse 1 (UV)")
    step = study.steps[0]
    study.upsert_step(dataclasses.replace(
        step, comparisons=step.comparisons[:1], excluded=("System pulse 2 (UV)",)
    ))
    study.remove_comparison("System pulse 2 (UV)")
    assert study.steps[0].excluded == ()
    assert "System pulse 2 (UV)" not in [c.name for c in study.comparisons]


def test_replace_comparison_renames_in_place_and_in_steps(study, calls):
    renamed = dataclasses.replace(study.comparison("System pulse 1 (UV)"), name="S-A2")

    study.replace_comparison("System pulse 1 (UV)", renamed)

    assert study.comparisons[0] is renamed and study.steps[0].comparisons[0] is renamed
    assert study.steps_using("S-A2") == ["Extra-column volume"]
    assert study.steps_using("System pulse 1 (UV)") == []
    assert calls == [1]
    with pytest.raises(ValueError, match="already exists"):
        study.replace_comparison("S-A2", dataclasses.replace(renamed, name="System pulse 2 (UV)"))
    with pytest.raises(KeyError):
        study.replace_comparison("nope", dataclasses.replace(renamed, name="nope"))


def test_species_gaps_and_explicit_transfer(study):
    periphery = study.initial_store.updated(
        {DISPERSION: {"SystemTracer": 4e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    )
    gaps = species_gaps(study.steps[1], periphery)
    assert sorted(gaps[DISPERSION]) == ["LargeTracer", "SmallTracer"]

    transferred = transfer_species(periphery, [DISPERSION], gaps[DISPERSION])

    assert DISPERSION not in species_gaps(study.steps[1], transferred)
    assert transferred.value(DISPERSION) == dict.fromkeys(
        ("SystemTracer", "SmallTracer", "LargeTracer"), 4e-7
    )
    provenance = transferred.entries[DISPERSION].provenance
    assert "transferred unchanged" in provenance.note and provenance.probe == "SystemTracer"


class TestSave:
    def test_a_new_folder_gets_every_data_file_including_imported_runs(self, study, tmp_path):
        x = np.linspace(0.0, 5.0, 51)
        run = ExperimentalRun(
            label="imported run",
            channels={"UV 1_280": Channel("UV 1_280", x, np.exp(-((x - 2.0) ** 2)))},
            x_basis="volume", x_unit="mL", markers=[(0.5, "Phase Elution")],
        )
        imported = dataclasses.replace(
            study.comparison("System pulse 1 (UV)"), name="S-imported",
            data_file="imported run.csv", run=run,
        )
        study.upsert_comparison(imported)

        path = study.save(tmp_path / "out" / "study.json")

        assert study.base_dir == path.parent
        files = {p.name for p in path.parent.iterdir()}
        assert files == {"study.json", *(c.data_file for c in study.comparisons)}
        assert (path.parent / "system_pulse_1_uv.csv").read_bytes() == (
            (DATA_DIR / "system_pulse_1_uv.csv").read_bytes()
        )
        loaded = Study.load(path).comparison("S-imported")
        np.testing.assert_array_equal(loaded.run.channels["UV 1_280"].values,
                                      run.channels["UV 1_280"].values)
        assert loaded.run.markers == run.markers

    def test_saving_again_writes_nothing_new(self, study, tmp_path):
        path = study.save(tmp_path / "study.json")
        before = {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.csv")}
        Study.load(path).save(path)
        assert {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.csv")} == before

    def test_never_overwrites_a_different_file(self, study, tmp_path):
        (tmp_path / "system_pulse_1_uv.csv").write_text("unrelated")
        study.save(tmp_path / "study.json")

        assert (tmp_path / "system_pulse_1_uv.csv").read_text() == "unrelated"
        assert study.comparison("System pulse 1 (UV)").data_file == "system_pulse_1_uv_2.csv"
        assert Study.load(tmp_path / "study.json").comparison("System pulse 1 (UV)").run


class TestComponents:
    def test_loading_without_components_derives_them(self, study):
        raw = study.to_dict()
        del raw["components"]
        loaded = Study.from_dict(raw, base_dir=MANIFEST.parent)
        assert loaded.components == [
            StudyComponent("SystemTracer", "small tracer"), *EXAMPLE_COMPONENTS[1:]
        ]

    def test_derivation_puts_salt_first_and_finds_a_common_role(self, study):
        small = dataclasses.replace(
            study.comparison("Small tracer pulse 1 (conductivity)"), name="small", probe="Acetone",
        )
        system = dataclasses.replace(
            study.comparison("System pulse 1 (UV)"), name="system", probe="Acetone",
        )
        untyped = dataclasses.replace(small, name="other", probe="Mystery", experiment_type=None)
        assert derive_components([system, small, gradient(study), untyped]) == [
            StudyComponent(SALT, "salt"),
            StudyComponent("Acetone", "small tracer"),
            StudyComponent("IgG", "protein"),
            StudyComponent("Mystery", "protein"),
        ]

    def test_adding_a_measurement_declares_its_probe_and_salt(self, study):
        study.upsert_comparison(gradient(study))
        assert study.components[0] == StudyComponent(SALT, "salt")
        assert study.component("IgG") == StudyComponent("IgG", "protein")
        assert study.measurements_using(SALT) == ["Gradient 1"]

    @pytest.mark.parametrize("name, role, match", [
        ("SmallTracer", "protein", "already declared"),
        ("X", "enzyme", "Unknown role"),
        (SALT, "protein", "reserved"),
        ("NaCl", "salt", "called 'Salt'"),
    ])
    def test_add_component_refuses(self, study, name, role, match):
        with pytest.raises(ValueError, match=match):
            study.add_component(name, role)

    def test_add_component_strips_and_puts_salt_first(self, study, calls):
        study.add_component(" IgG ", "protein")
        study.add_component(SALT, "salt")
        assert study.component("IgG").role == "protein"
        assert study.components[0].name == SALT
        assert calls == [1, 1]

    def test_rename_updates_every_measurement_when_no_values_are_stored(self, study):
        study.add_component("IgGG", "protein")
        study.upsert_comparison(gradient(study, component="IgGG"))
        step_view = study.comparison("Gradient 1")

        study.rename_component("IgGG", "IgG")

        renamed = study.comparison("Gradient 1")
        assert renamed is step_view
        assert renamed.probe == "IgG" and renamed.components == ["IgG"]
        assert renamed.recipe.components == [SALT, "IgG"]
        assert study.component("IgGG") is None
        assert renamed.problems() == []

    def test_rename_is_refused_while_values_are_stored(self, study, accept_periphery):
        with pytest.raises(ValueError, match="film diffusion \\(Column\\)"):
            study.rename_component("SmallTracer", "Acetone")
        accept_periphery()
        with pytest.raises(ValueError, match="accepted step Extra-column volume"):
            study.rename_component("SystemTracer", "Acetone")
        with pytest.raises(ValueError, match="already declared"):
            study.rename_component("SystemTracer", "SmallTracer")
        study.upsert_comparison(gradient(study))
        with pytest.raises(ValueError, match="fixed"):
            study.rename_component(SALT, "NaCl")

    def test_remove_is_refused_while_used(self, study):
        with pytest.raises(ValueError, match="System pulse 1"):
            study.remove_component("SystemTracer")
        study.add_component("IgG", "protein")
        study.remove_component("IgG")
        assert study.component("IgG") is None
        with pytest.raises(KeyError):
            study.remove_component("IgG")

    def test_role_mismatch_and_undeclared_probes_are_problems(self, study):
        comparison = study.comparison("Small tracer pulse 1 (conductivity)")
        assert study.measurement_problems(comparison) == []

        study.set_component_role("SmallTracer", "protein")
        assert study.component_problems(comparison) == [
            "Column pulse, small tracer (conductivity) uses 'SmallTracer' as a small tracer, "
            "but SmallTracer is declared as a protein."
        ]
        comparison.probe = "Unknown"
        assert study.component_problems(comparison) == ["'Unknown' is not a declared component."]
        comparison.probe = None
        assert "needs a small tracer" in study.component_problems(comparison)[0]
