from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from cadetgui.characterization.guide import (
    COMPONENT_ROLES,
    EXPERIMENT_TYPES,
    GLOSSARY,
    SALT,
    WORKFLOW_GUIDE,
    measurement_from_run,
    parameter_label,
)
from cadetgui.characterization.parameter_store import Provenance
from cadetgui.characterization.step_checks import study_steps_status
from cadetgui.characterization.study import Study, StudyComponent, derive_components

MANIFEST = (
    Path(__file__).parent.parent / "examples" / "data" / "characterization_akta" / "manifest.json"
)
FILM = "flow_sheet.column.film_diffusion"
DISPERSION = "flow_sheet.tubing_pre_column.axial_dispersion"
EXAMPLE_COMPONENTS = [
    StudyComponent("SystemTracer", "system tracer"),
    StudyComponent("SmallTracer", "small tracer"),
    StudyComponent("LargeTracer", "large tracer"),
]


@pytest.fixture
def study() -> Study:
    return Study.load(MANIFEST)


def _gradient(study: Study, name: str = "Gradient 1", component: str = "IgG"):
    source = study.comparison("Large tracer pulse 1 (UV)")
    return measurement_from_run(
        name, source.run, "UV 1_280", EXPERIMENT_TYPES["linear_gradient_elution"],
        source.recipe, component=component,
    )


def test_roles_and_experiment_types():
    assert list(COMPONENT_ROLES) == [
        "system tracer", "small tracer", "large tracer", "protein", "salt",
    ]
    assert all(COMPONENT_ROLES.values())
    roles = {t.id: t.probe_roles for t in EXPERIMENT_TYPES.values()}
    assert roles == {
        "system_pulse": ("small tracer", "system tracer"),
        "column_pulse_small_tracer": ("small tracer",),
        "column_pulse_large_tracer": ("large tracer",),
        "nonbinding_protein_pulse": ("protein",),
        "linear_gradient_elution": ("protein",),
        "breakthrough": ("protein",),
    }
    for term in ("component", "component role", *COMPONENT_ROLES):
        assert GLOSSARY[term]
    assert "**Components.**" in WORKFLOW_GUIDE
    assert WORKFLOW_GUIDE.index("**System.**") < WORKFLOW_GUIDE.index("**Components.**")


def test_example_declares_its_components_and_round_trips(study, tmp_path):
    assert study.components == EXAMPLE_COMPONENTS
    raw = json.loads(MANIFEST.read_text())
    assert raw["components"][0] == {"name": "SystemTracer", "role": "system tracer"}

    study.add_component("IgG", "protein")
    path = study.save(tmp_path / "study.json")
    loaded = Study.load(path)
    assert loaded.components == [*EXAMPLE_COMPONENTS, StudyComponent("IgG", "protein")]


def test_loading_without_components_derives_them(study):
    raw = study.to_dict()
    del raw["components"]
    loaded = Study.from_dict(raw, base_dir=MANIFEST.parent)
    assert loaded.components == [
        StudyComponent("SystemTracer", "small tracer"), *EXAMPLE_COMPONENTS[1:]
    ]


def test_derivation_puts_salt_first_and_finds_a_common_role(study):
    gradient = _gradient(study)
    small = dataclasses.replace(
        study.comparison("Small tracer pulse 1 (conductivity)"), name="small",
        probe="Acetone",
    )
    system = dataclasses.replace(
        study.comparison("System pulse 1 (UV)"), name="system", probe="Acetone",
    )
    untyped = dataclasses.replace(small, name="other", probe="Mystery", experiment_type=None)
    assert derive_components([system, small, gradient, untyped]) == [
        StudyComponent(SALT, "salt"),
        StudyComponent("Acetone", "small tracer"),
        StudyComponent("IgG", "protein"),
        StudyComponent("Mystery", "protein"),
    ]


def test_adding_a_measurement_declares_its_probe_and_salt(study):
    study.upsert_comparison(_gradient(study))
    assert study.components[0] == StudyComponent(SALT, "salt")
    assert study.component("IgG") == StudyComponent("IgG", "protein")
    assert study.measurements_using(SALT) == ["Gradient 1"]


def test_add_component_rules(study):
    calls = []
    study.add_listener(lambda: calls.append(1))
    study.add_component(" IgG ", "protein")
    assert study.component("IgG").role == "protein" and calls == [1]
    with pytest.raises(ValueError, match="already declared"):
        study.add_component("IgG", "protein")
    with pytest.raises(ValueError, match="Unknown role"):
        study.add_component("X", "enzyme")
    with pytest.raises(ValueError, match="reserved"):
        study.add_component(SALT, "protein")
    with pytest.raises(ValueError, match="called 'Salt'"):
        study.add_component("NaCl", "salt")
    study.add_component(SALT, "salt")
    assert study.components[0].name == SALT


def test_rename_updates_every_measurement_when_no_values_are_stored(study):
    study.add_component("IgGG", "protein")
    study.upsert_comparison(_gradient(study, component="IgGG"))
    step_view = study.comparison("Gradient 1")

    study.rename_component("IgGG", "IgG")

    renamed = study.comparison("Gradient 1")
    assert renamed is step_view
    assert renamed.probe == "IgG" and renamed.components == ["IgG"]
    assert renamed.recipe.components == [SALT, "IgG"]
    assert study.component("IgGG") is None and study.component("IgG").role == "protein"
    assert renamed.problems() == []


def test_rename_is_refused_while_values_are_stored_under_the_name(study):
    with pytest.raises(ValueError, match="film diffusion \\(Column\\)"):
        study.rename_component("SmallTracer", "Acetone")
    assert study.comparison("Small tracer pulse 1 (conductivity)").probe == "SmallTracer"

    study.accept("Extra-column volume", study.initial_store.updated(
        {DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    ))
    with pytest.raises(ValueError, match="accepted step Extra-column volume"):
        study.rename_component("SystemTracer", "Acetone")
    with pytest.raises(ValueError, match="already declared"):
        study.rename_component("SystemTracer", "SmallTracer")


def test_salt_cannot_be_renamed(study):
    study.upsert_comparison(_gradient(study))
    with pytest.raises(ValueError, match="fixed"):
        study.rename_component(SALT, "NaCl")


def test_remove_is_refused_while_used(study):
    with pytest.raises(ValueError, match="System pulse 1"):
        study.remove_component("SystemTracer")
    study.add_component("IgG", "protein")
    study.remove_component("IgG")
    assert study.component("IgG") is None
    with pytest.raises(KeyError):
        study.remove_component("IgG")


def test_role_mismatch_and_undeclared_probes_are_problems(study):
    comparison = study.comparison("Small tracer pulse 1 (conductivity)")
    assert study.measurement_problems(comparison) == []

    study.set_component_role("SmallTracer", "protein")
    assert study.component_problems(comparison) == [
        "Column pulse, small tracer (conductivity) uses 'SmallTracer' as a small tracer, "
        "but SmallTracer is declared as a protein."
    ]
    status = study_steps_status(study)[1]
    assert not status.ready
    assert any("declared as a protein" in p for p in status.problems)

    study.set_component_role("SystemTracer", "small tracer")
    system = study.comparison("System pulse 1 (UV)")
    assert study.component_problems(system) == []

    comparison.probe = "Unknown"
    assert study.component_problems(comparison) == ["'Unknown' is not a declared component."]
    comparison.probe = None
    assert "needs a small tracer" in study.component_problems(comparison)[0]


def test_species_gap_problems_name_the_component_and_the_step(study):
    study.accept("Extra-column volume", study.initial_store.updated(
        {DISPERSION: {"SystemTracer": 4.5e-7}},
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    ))
    problems = study_steps_status(study)[1].problems
    assert any(
        "Column packing needs axial dispersion (Tubing (pre column)) for SmallTracer, "
        "LargeTracer; Extra-column volume fitted it for SystemTracer" in p for p in problems
    )
    assert parameter_label(FILM) == "film diffusion (Column)"
