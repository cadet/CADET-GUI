from __future__ import annotations

from cadetgui.parameters import (
    get_co_group,
    get_parameter,
    get_parameters,
    required_parameters,
)


def test_column_shared_parameters_match_across_models():
    grm = get_parameters("column", "GeneralRateModel")
    lrmp = get_parameters("column", "LumpedRateModelWithPores")
    # bed_porosity means the same thing (same unit/description) for both models --
    # each is introspected live off its own model's descriptor, not shared/copied
    # data, so this checks they actually agree rather than just trusting they do.
    assert lrmp["bed_porosity"] == grm["bed_porosity"]


def test_get_parameters_returns_names_alphabetically():
    names = list(get_parameters("column", "GeneralRateModel"))
    assert names == sorted(names)


def test_column_shared_geometry_present_on_every_tubular_model():
    for model in ["GeneralRateModel", "LumpedRateModelWithPores", "LumpedRateModelWithoutPores"]:
        params = get_parameters("column", model)
        assert {"length", "diameter", "axial_dispersion"} <= params.keys()


def test_tubular_reactor_shares_column_geometry_and_axial_dispersion_is_really_component_dependent():
    # TubularReactor (the mixer/tubing dead-volume units InstrumentWidget now
    # renders real forms for) shares length/diameter with the real column
    # models -- same TubularReactorBase attributes. Its axial_dispersion is
    # genuinely component-dependent at the CADET-Process level too (same
    # SizedUnsignedList as a real column's) -- get_parameters() reports the
    # real shape live off the descriptor, not a GUI opinion about it.
    # cadetprocessadapter.py's `_FORCE_SCALAR` is what renders it as a plain
    # scalar with no multiplex toggle (see test_configuration.py /
    # test_instrument.py for that adapter-level behavior); this schema layer
    # has no say in it.
    params = get_parameters("column", "TubularReactor")
    assert {"length", "diameter", "axial_dispersion"} <= params.keys()
    assert params["axial_dispersion"]["component_dependent"] is True
    grm_axial_dispersion = get_parameter("column", "GeneralRateModel", "axial_dispersion")
    assert grm_axial_dispersion["component_dependent"] is True


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
        TubularReactor,
    )

    cs = ComponentSystem(2)
    column_models = {
        "GeneralRateModel": GeneralRateModel,
        "LumpedRateModelWithPores": LumpedRateModelWithPores,
        "LumpedRateModelWithoutPores": LumpedRateModelWithoutPores,
        "TubularReactor": TubularReactor,
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
        ("column", "TubularReactor"),
        ("column", "Cstr"),
        ("binding", "Linear"),
        ("binding", "Langmuir"),
        ("binding", "StericMassAction"),
    ]:
        params = get_parameters(category, model)
        for name in required_parameters(category, model):
            assert name in params, f"{category}/{model} required parameter {name!r} has no metadata"


def test_required_parameters_excludes_cstr_flow_rate():
    # Cstr._required_parameters (the class attribute CADET-Process's metaclass
    # builds) includes "flow_rate" -- but a constructed Cstr(...).required_parameters
    # doesn't (confirmed directly: CADET-Process does extra instance-level
    # filtering the class attribute never captures). required_parameters()
    # instantiates a real object rather than trusting the class attribute,
    # specifically to get this right -- a naive class-level read would wrongly
    # add "flow_rate" here, which cadetprocessadapter.py has no metadata or
    # seed default for (see ARCHITECTURE.md/REQUIREMENTS.md item #22).
    assert required_parameters("column", "Cstr") == ["init_liquid_volume"]


def test_default_is_live_where_cadetprocess_has_one():
    # abstol etc. are the one place in this schema where CADET-Process itself
    # carries a real default (IDAS's own tolerances) -- introspected off the
    # descriptor now rather than hand-copied.
    assert get_parameter("solver", "SolverTimeIntegratorParameters", "abstol")["default"] == 1e-8
    assert get_parameter("solver", "SolverTimeIntegratorParameters", "errortest_sens")["default"] is False
    # Column/binding parameters are mandatory (CADET-Process's own default is
    # None -- there's nothing physically sensible to default a column length
    # to), so no "default" key should appear for them at all.
    assert "default" not in get_parameter("column", "GeneralRateModel", "length")


def test_every_registered_parameter_resolves_a_real_live_descriptor():
    # component_dependent/dtype/co_name/unit/description are all introspected
    # off the actual CADET-Process descriptor (cadetgui/parameters/__init__.py),
    # nothing hand-typed. `get_parameters()` only includes names that already
    # resolve to a real descriptor (see `_descriptor` -- q/cp/surface_diffusion
    # resolve via their `_name`-prefixed private descriptor), so this test is
    # mostly a smoke check that every registered (category, model) still does,
    # everywhere _MODEL_CLASSES claims a model, in one place.
    for category, model in [
        ("column", "GeneralRateModel"),
        ("column", "LumpedRateModelWithPores"),
        ("column", "LumpedRateModelWithoutPores"),
        ("column", "TubularReactor"),
        ("column", "Cstr"),
        ("binding", "NoBinding"),
        ("binding", "Linear"),
        ("binding", "Langmuir"),
        ("binding", "StericMassAction"),
        ("solver", "SolverTimeIntegratorParameters"),
    ]:
        for name, meta in get_parameters(category, model).items():
            assert "dtype" in meta, f"{category}/{model}/{name} has no live dtype"
            assert "component_dependent" in meta, f"{category}/{model}/{name} has no live shape"
            assert "co_name" in meta, f"{category}/{model}/{name} has no live co_name"
            assert "unit" in meta, f"{category}/{model}/{name} has no live unit"
            assert "description" in meta, f"{category}/{model}/{name} has no live description"


def test_unit_and_description_are_live_off_the_cadetprocess_descriptor():
    # unit=/description= are now set directly on the CADET-Process descriptors
    # (fau-advanced-separations/CADET-Process PR #435), not hand-copied into a
    # cadetgui-side JSON file -- get_parameter() just reads them straight off.
    length = get_parameter("column", "GeneralRateModel", "length")
    assert length["unit"] == "m"
    assert length["description"] == "Column length."


def test_get_co_group_is_the_one_thing_left_that_cant_come_from_live_introspection():
    # CADET-Process writes the solver group as a plain uppercase HDF5 path,
    # not through a cp_name<->co_name map the way column/binding parameters
    # are -- this is the one piece of metadata cadetgui still has to hand-type.
    assert get_co_group("SolverTimeIntegratorParameters") == "/solver/time_integrator"
    assert get_co_group("NotAModel") is None
