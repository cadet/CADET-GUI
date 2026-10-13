"""build_parameter_config_spec: field kinds, multiplex, optional fields, seed defaults."""

from __future__ import annotations

import pytest
from cadetgui.parameters import build_parameter_config_spec, parameter_defaults
from CADETProcess.processModel import (
    Cstr,
    GeneralRateModel,
    Langmuir,
    LumpedRateModelWithoutPores,
    NoBinding,
    StericMassAction,
    TubularReactor,
)


def _fields(spec):
    return {f.name: f for f in spec.fields}


@pytest.mark.parametrize(
    "cls, kinds",
    [
        (
            LumpedRateModelWithoutPores,
            {"axial_dispersion": "float_list", "diameter": "float", "length": "float"},
        ),
        (TubularReactor, {"axial_dispersion": "float", "length": "float"}),
        (Cstr, {"init_liquid_volume": "float"}),
        (Langmuir, {"capacity": "float_list", "is_kinetic": "bool"}),
        (StericMassAction, {"capacity": "float", "characteristic_charge": "float_list"}),
        (NoBinding, {}),
    ],
)
def test_field_kinds_follow_the_live_metadata(component_system, cls, kinds):
    fields = _fields(build_parameter_config_spec(cls(component_system, name="x")))

    assert {name: fields[name].kind for name in kinds} == kinds
    assert list(fields) == sorted(n for n in fields if n != "is_kinetic") + (
        ["is_kinetic"] if "is_kinetic" in fields else []
    )
    for f in fields.values():
        per_component = tuple(component_system.names) if f.kind == "float_list" else None
        assert f.component_names == per_component, f.name
    assert bool(fields) == (cls is not NoBinding)


@pytest.mark.parametrize("multiplexed, kind", [(True, "float_list"), (False, "float")])
def test_multiplex_toggles_per_component_editing(component_system, multiplexed, kind):
    column = GeneralRateModel(component_system, name="column")

    spec = build_parameter_config_spec(column, multiplex={"film_diffusion": multiplexed})

    assert _fields(spec)["film_diffusion"].kind == kind


def test_include_optional_adds_parameters_the_object_holds(component_system):
    column = LumpedRateModelWithoutPores(component_system, name="column")

    required = _fields(build_parameter_config_spec(column))
    every = _fields(build_parameter_config_spec(column, include_optional=True))

    assert required.keys() < every.keys()
    assert "flow_direction" in every


@pytest.mark.parametrize(
    "cls, name, seed",
    [
        (LumpedRateModelWithoutPores, "diameter", 0.005),
        (LumpedRateModelWithoutPores, "length", 0.05),
        (Cstr, "init_liquid_volume", 1e-6),
        (Langmuir, "capacity", [0.0, 0.0]),
    ],
)
def test_unset_parameters_start_from_seed_defaults(component_system, cls, name, seed):
    obj = cls(component_system, name="x")

    assert _fields(build_parameter_config_spec(obj))[name].default == seed
    assert parameter_defaults(obj, [name]) == {name: seed}


def test_spec_starts_from_current_values_and_build_writes_them_back(component_system):
    column = LumpedRateModelWithoutPores(component_system, name="column")
    column.length = 0.2
    spec = build_parameter_config_spec(column, multiplex={"axial_dispersion": False})
    assert _fields(spec)["length"].default == 0.2
    assert _fields(spec)["axial_dispersion"].kind == "float"

    built = spec.build({"length": 0.3, "diameter": "0.01", "axial_dispersion": 2e-7})

    assert built is column
    assert (column.length, column.diameter) == (0.3, 0.01)
    assert column.axial_dispersion == [2e-7, 2e-7]
