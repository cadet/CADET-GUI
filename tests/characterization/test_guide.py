"""The chain guide: experiment types, the default chain, measurements from runs, role fixes."""
from __future__ import annotations

import numpy as np
import pytest
from cadetgui.characterization.comparison import Comparison
from cadetgui.characterization.guide import (
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    SALT,
    STEP_TYPE_HELP,
    find_injection_marker,
    guide_for_step,
    measurement_from_run,
    new_step_setup,
    role_fix,
    with_implied_values,
)
from cadetgui.characterization.parameter_store import (
    ChainError,
    ParameterStore,
    check_chain,
    spec_for,
)
from cadetgui.characterization.stages import STAGES, describe_stage
from cadetgui.instrument.process_builder import build_process
from cadetgui.instrument.system import UNIT_LABELS
from cadetgui.io.configuration_store import ConfigurationState, InstrumentState
from cadetgui.io.experimental_data import Channel, ExperimentalRun
from cadetgui.process_model.values import has_parameter

from characterization.synthetic import FILM

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


def akta_run(markers):
    volume = np.linspace(0.0, 5.0, 501)
    peak = np.exp(-0.5 * ((volume - 2.0) / 0.1) ** 2)
    return ExperimentalRun(
        label="run.csv",
        channels={
            "UV 1_280": Channel("UV 1_280", volume, 1.0 + 10 * peak, "mAU"),
            "Cond": Channel("Cond", volume[::2], 40.0 + peak[::2], "mS/cm"),
        },
        x_basis="volume", x_unit="mL", markers=markers,
    )


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


@pytest.mark.parametrize("guide", DEFAULT_CHAIN, ids=lambda g: g.id)
def test_every_chain_step_is_complete(guide):
    assert guide.determines and guide.reading_results and guide.advice
    assert set(guide.system_units) <= set(UNIT_LABELS)
    for type_id in guide.experiment_types:
        assert EXPERIMENT_TYPES[type_id].step_id == guide.id
    assert new_step_setup(guide, []).stage == guide.stage
    assert STEP_TYPE_HELP[guide.stage]


def test_default_chain_is_consistent_in_order_only():
    processes = [build_process(t.apply(BASE, component="Probe")) for t in EXPERIMENT_TYPES.values()]
    setups = [new_step_setup(g, []) for g in DEFAULT_CHAIN]
    paths = {p for s in setups for p in (*s.requires, *s.provides)}
    specs = {
        path: spec_for(next(p for p in processes if has_parameter(p, path)), path)
        for path in paths
    }
    assert set(STEP_TYPE_HELP) == set(STAGES)
    check_chain([s.step for s in setups], ParameterStore(specs=specs))
    with pytest.raises(ChainError):
        check_chain([s.step for s in reversed(setups)], ParameterStore(specs=specs))


def test_apply_is_pure_and_maps_species_by_name():
    experiment_type = EXPERIMENT_TYPES["column_pulse_small_tracer"]
    recipe = experiment_type.apply(BASE, component="B")
    assert BASE.components == ["A", "B"]
    assert recipe.column_values["film_diffusion"] == [2e-5]
    assert recipe.model_values["c_sample"] == [0.0]
    assert experiment_type.apply(BASE, component="New").model_values["c_sample"] == [3.0]
    with pytest.raises(ValueError):
        EXPERIMENT_TYPES["linear_gradient_elution"].apply(BASE, component=SALT)


def test_apply_reproduces_the_example_recipes(study):
    small = study.comparison("Small tracer pulse 1 (conductivity)").recipe
    large = EXPERIMENT_TYPES["column_pulse_large_tracer"].apply(small, component="LargeTracer")
    assert large == study.comparison("Large tracer pulse 1 (UV)").recipe
    system = EXPERIMENT_TYPES["system_pulse"].apply(small, component="SystemTracer")
    expected = study.comparison("System pulse 1 (UV)").recipe
    assert system.instrument == expected.instrument
    assert system.model_values["c_sample"] == expected.model_values["c_sample"]


def test_large_tracer_implies_pore_exclusion():
    experiment_type = EXPERIMENT_TYPES["column_pulse_large_tracer"]
    (entry,) = experiment_type.store_entries("Dextran").values()
    assert entry.value == {"Dextran": 0.0} and "assumed" in entry.provenance.note
    store = with_implied_values(ParameterStore(), experiment_type, "Dextran")
    assert store.spec(FILM).species_indexed and store.value(FILM, "Dextran") == 0.0
    assert EXPERIMENT_TYPES["system_pulse"].store_entries("X") == {}


@pytest.mark.parametrize("type_id, channel, markers, marker", [
    ("column_pulse_small_tracer", "Cond",
     [(0.0, "Phase Equilibration"), (0.5, "Phase Elution")], "Phase Elution"),
    ("linear_gradient_elution", "UV 1_280",
     [(0.0, "Phase Sample Application"), (1.0, "Phase Elution")], "Phase Sample Application"),
])
def test_measurement_from_run(type_id, channel, markers, marker):
    experiment_type = EXPERIMENT_TYPES[type_id]
    comparison = measurement_from_run(
        "M1", akta_run(markers), channel, experiment_type, BASE, component="Probe"
    )
    assert comparison.problems() == []
    assert comparison.injection_marker == marker
    assert comparison.solution_path == experiment_type.solution_path
    assert comparison.experiment_type == type_id
    assert (comparison.recipe.components[0] == SALT) == experiment_type.with_salt
    assert Comparison.from_dict(comparison.to_dict()).experiment_type == type_id
    assert find_injection_marker(akta_run([(0.0, "Phase Equilibration")])) is None


def test_new_step_setup_rejects_foreign_experiment_types():
    comparison = measurement_from_run(
        "S", akta_run([(0.5, "Phase Elution")]), "UV 1_280", EXPERIMENT_TYPES["system_pulse"],
        BASE, component="Acetone",
    )
    setup = new_step_setup(CHAIN_BY_ID["system_periphery"], [comparison])
    assert setup.name == "Extra-column volume"
    assert setup.stage == "tubing" and setup.options == {"tubing": "tubing_pre_column"}
    assert guide_for_step(setup).id == "system_periphery"
    with pytest.raises(ValueError):
        new_step_setup(CHAIN_BY_ID["column_packing"], [comparison])


def test_role_fix_offers_a_role_only_when_the_other_uses_accept_it(study):
    small = EXPERIMENT_TYPES["column_pulse_small_tracer"]
    large = EXPERIMENT_TYPES["column_pulse_large_tracer"]
    text, role = role_fix(study, "SystemTracer", small)
    assert role == "small tracer" and "needs a small tracer" in text
    text, role = role_fix(study, "SystemTracer", large)
    assert role is None and "System pulse 1 (UV)" in text
    assert role_fix(study, "SmallTracer", small) == ("", None)
    assert role_fix(study, "Unknown", small) == ("", None)
