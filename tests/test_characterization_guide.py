"""Tests for the lab-language characterization guide."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from cadetgui.cadetprocessadapter import UNIT_LABELS  # noqa: E402
from cadetgui.characterization.comparison import (  # noqa: E402
    Comparison,
    recipe_from_dict,
)
from cadetgui.characterization.guide import (  # noqa: E402
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    GLOSSARY,
    GLOSSARY_ALIASES,
    SALT,
    WORKFLOW_GUIDE,
    find_injection_marker,
    guide_for_step,
    measurement_from_run,
    new_step_setup,
    with_implied_values,
)
from cadetgui.characterization.parameter_store import (  # noqa: E402
    ChainError,
    ParameterStore,
    Provenance,
    check_chain,
    has_parameter,
    spec_for,
)
from cadetgui.characterization.stages import describe_stage  # noqa: E402
from cadetgui.characterization.step_checks import study_steps_status  # noqa: E402
from cadetgui.characterization.study import Study  # noqa: E402
from cadetgui.io.configuration_store import (  # noqa: E402
    ConfigurationState,
    InstrumentState,
)
from cadetgui.io.experimental_data import Channel, ExperimentalRun  # noqa: E402
from cadetgui.process_builder import build_process  # noqa: E402

DATA_DIR = Path(__file__).parents[1] / "examples" / "data" / "characterization_akta"

BASE = ConfigurationState(
    components=["A", "B"],
    column_key="General Rate Model (GRM)",
    binding_key="None",
    template_key="Pulse Injection",
    instrument=InstrumentState(include_sample_loop=True, sample_loop_volume=20e-9),
    column_values={"film_diffusion": [1e-5, 2e-5], "length": 0.02},
    model_values={"c_buffer_a": [0.0, 0.0], "c_sample": [3.0, 0.0], "flow_rate": 1e-8,
                  "cycle_time": 300.0},
)


@pytest.fixture(scope="module")
def manifest():
    return json.loads((DATA_DIR / "manifest.json").read_text())


@pytest.mark.parametrize("type_id", list(EXPERIMENT_TYPES))
def test_every_experiment_type_builds_and_feeds_its_step(type_id):
    experiment_type = EXPERIMENT_TYPES[type_id]
    recipe = experiment_type.apply(BASE, component="Probe")
    process = build_process(recipe)
    assert process.check_config()
    assert recipe.components[-1] == "Probe"
    assert (recipe.components[0] == SALT) == experiment_type.with_salt

    unit, _, port = experiment_type.solution_path.partition(".")
    assert unit in process.flow_sheet.units_dict and port in ("inlet", "outlet")

    guide = CHAIN_BY_ID[experiment_type.step_id]
    assert type_id in guide.experiment_types
    for variable in describe_stage(guide.stage, **guide.options):
        if variable.parameter_path is not None:
            assert has_parameter(process, variable.parameter_path), variable.name


def test_apply_is_pure_and_maps_species_by_name():
    experiment_type = EXPERIMENT_TYPES["column_pulse_small_tracer"]
    recipe = experiment_type.apply(BASE, component="B")
    assert BASE.components == ["A", "B"]
    assert recipe.column_values["film_diffusion"] == [2e-5]
    assert recipe.model_values["c_sample"] == [0.0]
    assert recipe.model_values["flow_rate"] == 1e-8
    assert experiment_type.apply(BASE, component="New").model_values["c_sample"] == [3.0]


def test_apply_reproduces_the_example_recipes(manifest):
    recipes = {c["name"]: recipe_from_dict(c["recipe"]) for c in manifest["comparisons"]}
    large = EXPERIMENT_TYPES["column_pulse_large_tracer"].apply(
        recipes["Small tracer pulse 1 (conductivity)"], component="LargeTracer"
    )
    assert large == recipes["Large tracer pulse 1 (UV)"]
    system = EXPERIMENT_TYPES["system_pulse"].apply(
        recipes["Small tracer pulse 1 (conductivity)"], component="SystemTracer"
    )
    assert system.instrument == recipes["System pulse 1 (UV)"].instrument
    assert (
        system.model_values["c_sample"] == recipes["System pulse 1 (UV)"].model_values["c_sample"]
    )


def test_large_tracer_implies_pore_exclusion():
    experiment_type = EXPERIMENT_TYPES["column_pulse_large_tracer"]
    (entry,) = experiment_type.store_entries("Dextran").values()
    assert entry.value == {"Dextran": 0.0}
    assert "assumed" in entry.provenance.note

    store = with_implied_values(ParameterStore(), experiment_type, "Dextran")
    path = "flow_sheet.column.film_diffusion"
    assert store.spec(path).species_indexed
    assert store.value(path, "Dextran") == 0.0
    assert EXPERIMENT_TYPES["system_pulse"].store_entries("X") == {}


def test_salt_is_reserved_for_salt_types():
    with pytest.raises(ValueError):
        EXPERIMENT_TYPES["linear_gradient_elution"].apply(BASE, component=SALT)


def _chain_specs():
    processes = [
        build_process(t.apply(BASE, component="Probe")) for t in EXPERIMENT_TYPES.values()
    ]
    setups = [new_step_setup(g, []) for g in DEFAULT_CHAIN]
    paths = {p for s in setups for p in (*s.requires, *s.provides)}
    return {
        path: spec_for(next(p for p in processes if has_parameter(p, path)), path)
        for path in paths
    }, setups


def test_default_chain_is_consistent():
    specs, setups = _chain_specs()
    check_chain([s.step for s in setups], ParameterStore(specs=specs))
    with pytest.raises(ChainError):
        check_chain([s.step for s in reversed(setups)], ParameterStore(specs=specs))


def test_chain_guides_are_complete():
    assert [g.title for g in DEFAULT_CHAIN] == [
        "Extra-column volume", "Column packing", "Particle transport", "Binding", "Capacity",
    ]
    for guide in DEFAULT_CHAIN:
        assert guide.determines and guide.reading_results
        assert 1 <= len(guide.advice) <= 3
        assert set(guide.system_units) <= set(UNIT_LABELS)
        for type_id in guide.experiment_types:
            assert EXPERIMENT_TYPES[type_id].step_id == guide.id


def test_glossary_and_workflow_cover_the_terms():
    for term in (
        "comparison", "measurement", "recipe", "flow path", "observation point",
        "injection marker", "alignment", "baseline window", "normalization", "prior",
        "posterior", "parameter store", "provenance", "probe", "species transfer",
        "Pareto candidate", "best average", "fixed variable", "NRMSE",
        "extra-column volume", "characterization step", "step type",
    ):
        assert GLOSSARY[term]
    assert GLOSSARY_ALIASES["frozen variable"] == "fixed variable"
    assert "frozen variable" not in GLOSSARY
    for guide in DEFAULT_CHAIN:
        assert guide.title in WORKFLOW_GUIDE


def _akta_run(label, markers):
    volume = np.linspace(0.0, 5.0, 501)
    peak = np.exp(-0.5 * ((volume - 2.0) / 0.1) ** 2)
    return ExperimentalRun(
        label=label,
        channels={
            "UV 1_280": Channel("UV 1_280", volume, 1.0 + 10 * peak, "mAU"),
            "Cond": Channel("Cond", volume[::2], 40.0 + peak[::2], "mS/cm"),
        },
        x_basis="volume",
        x_unit="mL",
        markers=markers,
    )


def test_measurement_from_run_pulse():
    run = _akta_run("run1.csv", [(0.0, "Phase Equilibration"), (0.5, "Phase Elution")])
    experiment_type = EXPERIMENT_TYPES["column_pulse_small_tracer"]
    comparison = measurement_from_run("M1", run, "Cond", experiment_type, BASE, component="Acetone")
    assert comparison.problems() == []
    assert comparison.injection_marker == "Phase Elution"
    assert comparison.solution_path == "tubing_detectors.outlet"
    assert comparison.experiment_type == "column_pulse_small_tracer"
    assert comparison.normalization == {"kind": "area", "target_area": pytest.approx(3.0 * 20e-9)}
    assert Comparison.from_dict(comparison.to_dict()).experiment_type == comparison.experiment_type


def test_measurement_from_run_gradient():
    run = _akta_run("lge.csv", [(0.0, "Phase Sample Application"), (1.0, "Phase Elution")])
    comparison = measurement_from_run(
        "LGE", run, "UV 1_280", EXPERIMENT_TYPES["linear_gradient_elution"], BASE,
        component="mAb",
    )
    assert comparison.problems() == []
    assert comparison.injection_marker == "Phase Sample Application"
    assert comparison.recipe.components == [SALT, "mAb"]
    assert comparison.flow_rate == 1e-8


def test_find_injection_marker_none_without_match():
    run = _akta_run("x", [(0.0, "Phase Equilibration")])
    assert find_injection_marker(run) is None


def test_new_step_setup_rejects_foreign_experiment_types():
    run = _akta_run("run1.csv", [(0.5, "Phase Elution")])
    comparison = measurement_from_run(
        "S", run, "UV 1_280", EXPERIMENT_TYPES["system_pulse"], BASE, component="Acetone"
    )
    setup = new_step_setup(CHAIN_BY_ID["system_periphery"], [comparison])
    assert setup.stage == "tubing" and setup.options == {"tubing": "tubing_pre_column"}
    assert setup.name == "Extra-column volume"
    assert guide_for_step(setup).id == "system_periphery"
    with pytest.raises(ValueError):
        new_step_setup(CHAIN_BY_ID["column_packing"], [comparison])


def test_example_manifest_carries_experiment_types(manifest):
    types = {c["name"]: c["experiment_type"] for c in manifest["comparisons"]}
    assert types == {
        "System pulse 1 (UV)": "system_pulse",
        "System pulse 2 (UV)": "system_pulse",
        "Small tracer pulse 1 (conductivity)": "column_pulse_small_tracer",
        "Small tracer pulse 2 (conductivity)": "column_pulse_small_tracer",
        "Large tracer pulse 1 (UV)": "column_pulse_large_tracer",
        "Large tracer pulse 2 (UV)": "column_pulse_large_tracer",
    }


def test_study_steps_status_before_and_after_accepting_step_one():
    study = Study.load(DATA_DIR / "manifest.json")
    assert [guide_for_step(s).id for s in study.steps] == ["system_periphery", "column_packing"]

    first, second = study_steps_status(study)
    assert first.ready and not first.accepted and first.next_action == "Run the fit."
    assert first.measurements == {"system_pulse": ["System pulse 1 (UV)", "System pulse 2 (UV)"]}
    assert second.measurements == {
        "column_pulse_small_tracer": [
            "Small tracer pulse 1 (conductivity)", "Small tracer pulse 2 (conductivity)",
        ],
        "column_pulse_large_tracer": ["Large tracer pulse 1 (UV)", "Large tracer pulse 2 (UV)"],
    }
    assert not second.ready
    assert second.next_action.endswith("accept Extra-column volume first.")

    (first,) = study_steps_status(study, fitted={"Extra-column volume"})[:1]
    assert first.next_action == "Choose a Pareto candidate and accept it."

    posterior = study.initial_store.updated(
        {
            "flow_sheet.tubing_pre_column.length": 0.4,
            "flow_sheet.tubing_pre_column.axial_dispersion": {"SystemTracer": 5e-7},
        },
        Provenance(step="Extra-column volume", probe="SystemTracer"),
    )
    study.accept("Extra-column volume", posterior)

    first, second = study_steps_status(study)
    assert first.accepted and first.next_action == "Accepted. Continue with Column packing."
    assert second.species_gaps == {
        "flow_sheet.tubing_pre_column.axial_dispersion": ["SmallTracer", "LargeTracer"],
    }
    assert not second.ready
    assert "Carry them over explicitly" in second.next_action


def test_every_step_type_has_one_line_of_help_and_no_stage_wording():
    from cadetgui.characterization.guide import STEP_TYPE_HELP, step_type_help
    from cadetgui.characterization.stages import STAGES

    assert set(STEP_TYPE_HELP) == set(STAGES)
    for stage_id in STAGES:
        assert step_type_help(stage_id) and "\n" not in step_type_help(stage_id)
    texts = [*STEP_TYPE_HELP.values(), *GLOSSARY.values(), WORKFLOW_GUIDE]
    texts += [s.label for s in STAGES.values()]
    assert not any("stage" in t.lower() or "fit step" in t.lower() for t in texts)


def test_role_fix_offers_a_role_only_when_the_other_uses_accept_it():
    from cadetgui.characterization.guide import role_fix

    study = Study.load(DATA_DIR / "manifest.json")
    small = EXPERIMENT_TYPES["column_pulse_small_tracer"]
    large = EXPERIMENT_TYPES["column_pulse_large_tracer"]

    text, role = role_fix(study, "SystemTracer", small)
    assert role == "small tracer"
    assert text == (
        "SystemTracer is declared as a system tracer. This experiment needs a small tracer."
    )
    text, role = role_fix(study, "SystemTracer", large)
    assert role is None and "System pulse 1 (UV)" in text and "need that role" in text
    assert role_fix(study, "SmallTracer", small) == ("", None)
    assert role_fix(study, "Unknown", small) == ("", None)
