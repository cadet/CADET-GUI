"""Parameter metadata read live from CADET-Process for every registered model."""

from __future__ import annotations

import pytest
from cadetgui.parameters import describe_parameter, get_parameter, get_parameters
from cadetgui.parameters.metadata import _MODEL_CLASSES
from CADETProcess.processModel import ComponentSystem, Inlet, Langmuir

KEYS = {"dtype", "component_dependent", "co_name", "unit", "description"}


@pytest.mark.parametrize("category, model", sorted(_MODEL_CLASSES))
def test_every_registered_model_has_complete_sorted_metadata(category, model):
    params = get_parameters(category, model)

    assert list(params) == sorted(params)
    for name, meta in params.items():
        assert KEYS <= meta.keys(), name
        assert meta["dtype"] in {"float", "int", "bool"}, name
        assert meta.get("min", -1e300) <= meta.get("max", 1e300), name
        if category == "solver":
            assert meta["component_dependent"] is False and meta["co_name"] is None

    if category != "solver":
        cls = _MODEL_CLASSES[(category, model)]
        assert set(cls(ComponentSystem(2), name="x").required_parameters) <= params.keys()


def test_unregistered_model_raises():
    with pytest.raises(KeyError):
        get_parameters("column", "NotAModel")


@pytest.mark.parametrize(
    "category, model, name, component_dependent",
    [
        ("column", "GeneralRateModel", "axial_dispersion", True),
        ("column", "GeneralRateModel", "length", False),
        ("binding", "Langmuir", "capacity", True),
        ("binding", "StericMassAction", "capacity", False),
    ],
)
def test_component_dependence_follows_the_descriptor(category, model, name, component_dependent):
    assert get_parameter(category, model, name)["component_dependent"] is component_dependent


@pytest.mark.usefixtures("cadet_process_descriptor_metadata")
def test_unit_description_and_default_are_read_off_the_descriptor():
    length = get_parameter("column", "GeneralRateModel", "length")
    assert (length["unit"], length["description"]) == (r"\mathrm{m}", "Column length.")
    assert "default" not in length
    assert get_parameter("solver", "SolverTimeIntegratorParameters", "abstol")["default"] == 1e-8
    assert (
        get_parameter("binding", "Langmuir", "adsorption_rate")["unit"]
        != get_parameter("binding", "Linear", "adsorption_rate")["unit"]
    )


def test_describe_parameter_works_on_any_object():
    cs = ComponentSystem(1)
    assert describe_parameter(Inlet(cs, "inlet"), "flow_rate")[1] == "Volumetric flow rate."
    assert describe_parameter(Langmuir(cs, "b"), "capacity")[0]
    assert describe_parameter(Langmuir(cs, "b"), "not_a_parameter") == ("", "")
