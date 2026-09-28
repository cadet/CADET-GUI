from __future__ import annotations

import pytest
from cadetgui.parameters import get_parameter, get_parameters
from CADETProcess.processModel import (
    ComponentSystem,
    Cstr,
    GeneralRateModel,
    Langmuir,
    Linear,
    LumpedRateModelWithoutPores,
    LumpedRateModelWithPores,
    NoBinding,
    StericMassAction,
    TubularReactor,
)

_COLUMN_CLASSES = {
    "GeneralRateModel": GeneralRateModel,
    "LumpedRateModelWithPores": LumpedRateModelWithPores,
    "LumpedRateModelWithoutPores": LumpedRateModelWithoutPores,
    "TubularReactor": TubularReactor,
    "Cstr": Cstr,
}
_BINDING_CLASSES = {
    "NoBinding": NoBinding,
    "Linear": Linear,
    "Langmuir": Langmuir,
    "StericMassAction": StericMassAction,
}
_REGISTERED = [
    *(("column", name) for name in _COLUMN_CLASSES),
    *(("binding", name) for name in _BINDING_CLASSES),
    ("solver", "SolverTimeIntegratorParameters"),
]


def test_get_parameters_returns_names_alphabetically():
    names = list(get_parameters("column", "GeneralRateModel"))
    assert names == sorted(names)


def test_get_parameters_rejects_an_unregistered_model():
    with pytest.raises(KeyError):
        get_parameters("column", "NotAModel")


def test_shared_parameters_agree_across_column_models():
    grm = get_parameters("column", "GeneralRateModel")
    lrmp = get_parameters("column", "LumpedRateModelWithPores")
    assert lrmp["bed_porosity"] == grm["bed_porosity"]


@pytest.mark.parametrize("model", [m for m in _COLUMN_CLASSES if m != "Cstr"])
def test_tubular_models_share_column_geometry_and_component_dependent_dispersion(model):
    params = get_parameters("column", model)

    assert {"length", "diameter", "axial_dispersion"} <= params.keys()
    assert params["axial_dispersion"]["component_dependent"] is True


def test_cstr_has_no_tubular_geometry():
    params = get_parameters("column", "Cstr")

    assert not {"length", "diameter", "axial_dispersion"} & params.keys()
    assert "init_liquid_volume" in params


def test_langmuir_capacity_is_component_dependent_but_sma_capacity_is_not():
    langmuir_capacity = get_parameter("binding", "Langmuir", "capacity")
    sma_capacity = get_parameter("binding", "StericMassAction", "capacity")

    assert langmuir_capacity["component_dependent"] is True
    assert sma_capacity["component_dependent"] is False
    assert langmuir_capacity["co_name"] != sma_capacity["co_name"]


def test_solver_parameters_are_never_component_dependent():
    params = get_parameters("solver", "SolverTimeIntegratorParameters")

    assert params
    assert all(p["component_dependent"] is False for p in params.values())


@pytest.mark.parametrize(("category", "model"), _REGISTERED)
def test_every_parameter_carries_the_live_metadata_keys(category, model):
    params = get_parameters(category, model)

    assert params
    keys = {"dtype", "component_dependent", "co_name", "unit", "description"}
    for name, meta in params.items():
        assert keys <= meta.keys(), name


@pytest.mark.parametrize(
    ("category", "classes"), [("column", _COLUMN_CLASSES), ("binding", _BINDING_CLASSES)]
)
def test_every_required_parameter_of_a_real_model_has_metadata(category, classes):
    cs = ComponentSystem(2)
    for name, cls in classes.items():
        required = set(cls(cs, name="x").required_parameters)
        assert required <= get_parameters(category, name).keys(), name


@pytest.mark.usefixtures("cadet_process_descriptor_metadata")
def test_adsorption_rate_unit_differs_between_langmuir_and_linear():
    assert (
        get_parameter("binding", "Langmuir", "adsorption_rate")["unit"]
        != get_parameter("binding", "Linear", "adsorption_rate")["unit"]
    )


@pytest.mark.usefixtures("cadet_process_descriptor_metadata")
def test_default_is_present_only_where_cadetprocess_has_one():
    solver = "SolverTimeIntegratorParameters"
    assert get_parameter("solver", solver, "abstol")["default"] == 1e-8
    assert get_parameter("solver", solver, "errortest_sens")["default"] is False
    assert "default" not in get_parameter("column", "GeneralRateModel", "length")


@pytest.mark.usefixtures("cadet_process_descriptor_metadata")
def test_unit_and_description_are_read_off_the_descriptor():
    length = get_parameter("column", "GeneralRateModel", "length")
    dispersion = get_parameter("column", "GeneralRateModel", "axial_dispersion")

    assert length["unit"] == r"\mathrm{m}"
    assert length["description"] == "Column length."
    assert dispersion["unit"] == r"\frac{\mathrm{m}^{2}_{\mathrm{IV}}}{\mathrm{s}}"
