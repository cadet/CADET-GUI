from __future__ import annotations

from cadetgui.parameters import get_parameter, get_parameters, required_parameters


def test_column_shared_parameters_resolve_via_ref():
    grm = get_parameters("column", "GeneralRateModel")
    lrmp = get_parameters("column", "LumpedRateModelWithPores")
    # bed_porosity is a $ref in LumpedRateModelWithPores pointing at GeneralRateModel's
    # entry -- must resolve to the same actual dict, not stay a literal {"$ref": ...}.
    assert lrmp["bed_porosity"] == grm["bed_porosity"]
    assert "$ref" not in str(lrmp["bed_porosity"])


def test_column_shared_geometry_present_on_every_tubular_model():
    for model in ["GeneralRateModel", "LumpedRateModelWithPores", "LumpedRateModelWithoutPores"]:
        params = get_parameters("column", model)
        assert {"length", "diameter", "axial_dispersion"} <= params.keys()


def test_cstr_has_no_shared_tubular_geometry():
    params = get_parameters("column", "Cstr")
    assert "length" not in params
    assert "diameter" not in params
    assert "axial_dispersion" not in params
    assert "init_liquid_volume" in params


def test_langmuir_capacity_is_component_dependent_but_sma_capacity_is_not():
    langmuir_capacity = get_parameter("binding", "Langmuir", "capacity")
    sma_capacity = get_parameter("binding", "StericMassAction", "capacity")
    assert langmuir_capacity["component_dependent"] is True
    assert sma_capacity["component_dependent"] is False
    # same CADET-Process attribute name, different CADET-Core field -- the whole
    # reason this schema is nested per-model rather than one flat dict.
    assert langmuir_capacity["co_name"] != sma_capacity["co_name"]


def test_adsorption_rate_unit_differs_between_langmuir_and_linear():
    assert (
        get_parameter("binding", "Langmuir", "adsorption_rate")["unit"]
        != get_parameter("binding", "Linear", "adsorption_rate")["unit"]
    )


def test_solver_category_parameters_are_never_component_dependent():
    params = get_parameters("solver", "SolverTimeIntegratorParameters")
    assert params
    assert all(p["component_dependent"] is False for p in params.values())


def test_required_parameters_match_real_cadetprocess_objects():
    """Cross-check against CADET-Process itself, not just internal consistency --
    this is the schema's actual ground-truth claim, so it must match the library
    it describes."""
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
    )

    cs = ComponentSystem(2)
    column_models = {
        "GeneralRateModel": GeneralRateModel,
        "LumpedRateModelWithPores": LumpedRateModelWithPores,
        "LumpedRateModelWithoutPores": LumpedRateModelWithoutPores,
    }
    for name, cls in column_models.items():
        obj = cls(cs, name="x")
        assert set(required_parameters("column", name)) == set(obj.required_parameters)

    assert set(required_parameters("column", "Cstr")) == set(Cstr(cs, name="x").required_parameters)

    binding_models = {"Linear": Linear, "Langmuir": Langmuir, "StericMassAction": StericMassAction}
    for name, cls in binding_models.items():
        obj = cls(cs, name="x")
        assert set(required_parameters("binding", name)) == set(obj.required_parameters)

    assert required_parameters("binding", "NoBinding") == NoBinding().required_parameters == []


def test_every_required_parameter_has_metadata():
    for category, model in [
        ("column", "GeneralRateModel"),
        ("column", "LumpedRateModelWithPores"),
        ("column", "LumpedRateModelWithoutPores"),
        ("column", "Cstr"),
        ("binding", "Linear"),
        ("binding", "Langmuir"),
        ("binding", "StericMassAction"),
    ]:
        params = get_parameters(category, model)
        for name in required_parameters(category, model):
            assert name in params, f"{category}/{model} required parameter {name!r} has no metadata"
