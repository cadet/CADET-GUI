from __future__ import annotations

import pytest
from cadetgui.characterization.stages import (
    STAGES,
    build_problem,
    describe_stage,
    write_targets,
)
from CADETProcess import CADETProcessError
from CADETProcess.characterization import setup_comparators
from CADETProcess.instruments import LCFlowSheet, PulseInjection
from CADETProcess.processModel import (
    ComponentSystem,
    LumpedRateModelWithPores,
    StericMassAction,
)
from CADETProcess.reference import ReferenceIO
from CADETProcess.simulator import Cadet

COMPONENT_SYSTEM = ComponentSystem(["Salt", "A"])


def _process(name: str = "pulse") -> PulseInjection:
    """A small real LRMP + SMA pulse process: fast to simulate, physically consistent."""
    flow_sheet = LCFlowSheet(
        COMPONENT_SYSTEM,
        sample_loop_volume=1e-7,
        ColumnModel=LumpedRateModelWithPores,
        BindingModel=StericMassAction,
        bypass_units=["tubing_post_column", "tubing_detectors"],
    )
    flow_sheet.mixer.init_liquid_volume = 1e-9
    flow_sheet.mixer.flow_rate = 1e-6
    flow_sheet.tubing_pre_injection.length = 0.2
    flow_sheet.tubing_pre_injection.diameter = 1e-3
    flow_sheet.tubing_pre_injection.axial_dispersion = 1e-7
    flow_sheet.tubing_pre_column.length = 0.1
    flow_sheet.tubing_pre_column.diameter = 1e-3
    flow_sheet.tubing_pre_column.axial_dispersion = 1e-7

    column = flow_sheet.column
    column.length = 0.1
    column.diameter = 0.01
    column.bed_porosity = 0.4
    column.particle_porosity = 0.6
    column.particle_radius = 5e-5
    column.axial_dispersion = 1e-7
    column.film_diffusion = [1e-5, 1e-5]
    column.discretization.ncol = 20

    binding = column.binding_model
    binding.is_kinetic = False
    binding.adsorption_rate = [0, 1.0]
    binding.desorption_rate = [1, 1]
    binding.characteristic_charge = [0, 5.0]
    binding.steric_factor = [0, 10.0]
    binding.capacity = 1000.0

    return PulseInjection(
        name, flow_sheet, c_buffer_a=[0, 0], c_sample=[0, 1.0], cycle_time=200.0, flow_rate=1e-6
    )


@pytest.fixture(scope="module")
def reference() -> ReferenceIO:
    """Synthetic reference from one fixed-seed simulation of `_process()` -- no measured data."""
    result = Cadet().simulate(_process("reference"))
    outlet = result.solution.column.outlet
    return ReferenceIO("reference", outlet.time, outlet.solution, component_system=COMPONENT_SYSTEM)


def _comparator(process, reference):
    (comparator,) = setup_comparators(
        process, reference, "column.outlet", metrics=["NRMSE"], components=["A"]
    )
    return comparator


# -- STAGES registry --------------------------------------------------------------------


def test_stage_ids_match_the_stable_set():
    assert set(STAGES) == {
        "tubing", "pre_injection", "bed", "particles", "capacity", "adsorption",
    }


@pytest.mark.parametrize(
    ("stage_id", "expected_options"),
    [
        ("tubing", {"tubing"}),
        ("pre_injection", set()),
        ("bed", {"include_particle_porosity"}),
        (
            "particles",
            {
                "include_axial_dispersion", "include_particle_porosity",
                "include_film_diffusion", "include_pore_diffusion", "component_index",
            },
        ),
        ("capacity", set()),
        (
            "adsorption",
            {
                "is_kinetic", "include_steric_factor", "include_film_diffusion",
                "include_pore_diffusion", "component_index",
            },
        ),
    ],
)
def test_stage_options_are_discovered_from_the_constructor_signature(stage_id, expected_options):
    assert set(STAGES[stage_id].options) == expected_options


# -- describe_stage -----------------------------------------------------------------------


def test_describe_stage_requires_options_with_no_constructor_default():
    with pytest.raises(ValueError, match="tubing"):
        describe_stage("tubing")


def test_describe_stage_rejects_an_unknown_option():
    with pytest.raises(ValueError, match="bogus"):
        describe_stage("bed", bogus=True)


def test_tubing_variable_names_follow_the_tubing_unit():
    variables = describe_stage("tubing", tubing="tubing_pre_column")
    assert [v.name for v in variables] == [
        "tubing_pre_column_length", "tubing_pre_column_axial_dispersion",
    ]
    assert [v.parameter_path for v in variables] == [
        "flow_sheet.tubing_pre_column.length", "flow_sheet.tubing_pre_column.axial_dispersion",
    ]
    assert not any(v.is_dependent for v in variables)

    renamed = describe_stage("tubing", tubing="tubing_pre_injection")
    assert [v.name for v in renamed] == [
        "tubing_pre_injection_length", "tubing_pre_injection_axial_dispersion",
    ]


def test_bed_default_options_omit_particle_porosity():
    default = describe_stage("bed")
    assert [v.name for v in default] == ["bed_porosity", "axial_dispersion"]

    with_porosity = describe_stage("bed", include_particle_porosity=True)
    assert [v.name for v in with_porosity] == [
        "bed_porosity", "axial_dispersion", "particle_porosity",
    ]


def test_particles_requires_at_least_one_include_flag():
    with pytest.raises(ValueError, match="include_"):
        describe_stage("particles")


def test_particles_variable_uses_component_index_for_its_indices():
    variables = describe_stage("particles", include_film_diffusion=True, component_index=1)
    (film_diffusion,) = variables
    assert film_diffusion.name == "film_diffusion"
    assert film_diffusion.indices == [1]


@pytest.mark.parametrize(
    ("options", "expected_names"),
    [
        (
            {"is_kinetic": False},
            {"characteristic_charge", "adsorption_rate"},
        ),
        (
            {"is_kinetic": True},
            {
                "characteristic_charge", "adsorption_rate", "desorption_rate",
                "equilibrium_constant", "kinetic_constant",
            },
        ),
    ],
)
def test_adsorption_kinetic_vs_rapid_equilibrium_variable_sets(options, expected_names):
    variables = describe_stage("adsorption", **options)
    assert {v.name for v in variables} == expected_names


def test_adsorption_kinetic_mode_marks_the_dependency_chain_as_dependent():
    variables = {v.name: v for v in describe_stage("adsorption", is_kinetic=True)}

    assert not variables["characteristic_charge"].is_dependent
    for name in ("adsorption_rate", "desorption_rate", "equilibrium_constant", "kinetic_constant"):
        assert variables[name].is_dependent

    # Free helper variables have no process write target.
    assert variables["equilibrium_constant"].parameter_path is None
    assert variables["kinetic_constant"].parameter_path is None
    # The derived binding-model rates still resolve to a real path.
    assert variables["adsorption_rate"].parameter_path == (
        "flow_sheet.column.binding_model.adsorption_rate"
    )


def test_capacity_has_a_single_non_dependent_variable():
    (capacity,) = describe_stage("capacity")
    assert capacity.name == "capacity"
    assert not capacity.is_dependent


# -- write_targets ------------------------------------------------------------------------


def test_write_targets_maps_names_to_parameter_paths():
    variables = describe_stage("bed", include_particle_porosity=True)
    assert write_targets(variables) == {
        "bed_porosity": "flow_sheet.column.bed_porosity",
        "axial_dispersion": "flow_sheet.column.axial_dispersion",
        "particle_porosity": "flow_sheet.column.particle_porosity",
    }


def test_write_targets_omits_free_helper_variables_but_keeps_derived_rates():
    variables = describe_stage("adsorption", is_kinetic=True)
    targets = write_targets(variables)
    assert "equilibrium_constant" not in targets
    assert "kinetic_constant" not in targets
    assert targets["adsorption_rate"] == "flow_sheet.column.binding_model.adsorption_rate"
    assert targets["desorption_rate"] == "flow_sheet.column.binding_model.desorption_rate"


# -- build_problem --------------------------------------------------------------------------


def test_build_problem_applies_bounds_and_excludes_frozen_variables(reference):
    process = _process("tubing_test")
    problem = build_problem(
        "tubing", process, _comparator(process, reference), Cadet(),
        options={"tubing": "tubing_pre_column"},
        bounds={"tubing_pre_column_length": (0.05, 0.2)},
        frozen={"tubing_pre_column_axial_dispersion"},
    )

    assert problem.variable_names == ["tubing_pre_column_length"]
    assert problem.variables_dict["tubing_pre_column_length"].lb == 0.05
    assert problem.variables_dict["tubing_pre_column_length"].ub == 0.2


def test_build_problem_clears_the_broken_plot_callback(reference):
    process = _process("callback_test")
    problem = build_problem(
        "tubing", process, _comparator(process, reference), Cadet(),
        options={"tubing": "tubing_pre_column"},
    )

    assert problem.n_callbacks == 0


def test_build_problem_without_frozen_evaluates_at_the_reference_value(reference):
    process = _process("eval_test")
    problem = build_problem(
        "tubing", process, _comparator(process, reference), Cadet(),
        options={"tubing": "tubing_pre_column"},
        frozen={"tubing_pre_column_axial_dispersion"},
    )

    # tubing_pre_column.length == 0.1 in `_process()`, the same value `reference` was
    # generated from, so NRMSE at that point should be (numerically) zero.
    objective = problem.evaluate_objectives([0.1])
    assert objective == pytest.approx([0.0], abs=1e-6)


def test_build_problem_frozen_dependent_variable_raises(reference):
    process = _process("kinetic_freeze_test")
    with pytest.raises(CADETProcessError, match="kinetic_constant"):
        build_problem(
            "adsorption", process, _comparator(process, reference), Cadet(),
            options={"is_kinetic": True}, frozen={"kinetic_constant"},
        )


def test_build_problem_kinetic_mode_dependent_variables_still_evaluate(reference):
    process = _process("kinetic_test")
    problem = build_problem(
        "adsorption", process, _comparator(process, reference), Cadet(),
        options={"is_kinetic": True}, frozen={"characteristic_charge"},
    )

    assert "characteristic_charge" not in problem.variable_names
    assert problem.independent_variable_names == ["equilibrium_constant", "kinetic_constant"]

    objective = problem.evaluate_objectives([1.0, 0.01])
    assert objective[0] < float("inf")


def test_build_problem_propagates_particles_missing_include_flag(reference):
    process = _process("particles_test")
    with pytest.raises(ValueError, match="include_"):
        build_problem("particles", process, _comparator(process, reference), Cadet())
