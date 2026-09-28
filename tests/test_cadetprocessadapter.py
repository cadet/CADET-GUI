from __future__ import annotations

import math

import pytest
from cadetgui.cadetprocessadapter import (
    build_parameter_config_spec,
    parse_float_list,
    require_finite_above,
    require_positive,
)
from CADETProcess.processModel import ComponentSystem, Langmuir


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1, 2;3\n4 5", [1.0, 2.0, 3.0, 4.0, 5.0]),
        ("  ", []),
        ("1e-3", [1e-3]),
        ((1, "2"), [1.0, 2.0]),
    ],
)
def test_parse_float_list_accepts_mixed_separators_and_sequences(raw, expected):
    assert parse_float_list(raw) == expected


def test_parse_float_list_rejects_a_non_number():
    with pytest.raises(ValueError):
        parse_float_list("1, abc")


@pytest.mark.parametrize("value", [0, -1.0])
def test_require_positive_rejects_zero_and_negative(value):
    with pytest.raises(ValueError):
        require_positive(value)


@pytest.mark.parametrize(
    ("kwargs", "value", "ok"),
    [
        ({}, 0.0, False),
        ({"inclusive": True}, 0.0, True),
        ({"minimum": 1.0}, 0.5, False),
        ({}, math.nan, False),
        ({}, math.inf, False),
        ({}, 3.0, True),
    ],
)
def test_require_finite_above(kwargs, value, ok):
    validate = require_finite_above(**kwargs)
    if ok:
        validate(value)
    else:
        with pytest.raises(ValueError):
            validate(value)


def test_build_parameter_config_spec_builds_sorted_fields_and_applies_values():
    binding = Langmuir(ComponentSystem(["A", "B"]), name="binding")

    spec = build_parameter_config_spec(binding)

    names = [f.name for f in spec.fields]
    assert names == [*sorted(binding.required_parameters), "is_kinetic"]
    capacity = next(f for f in spec.fields if f.name == "capacity")
    assert capacity.kind == "float_list"
    assert capacity.component_names == ("A", "B")

    spec.build({"capacity": "1.5, 2.5", "is_kinetic": False})

    assert list(binding.capacity) == [1.5, 2.5]
    assert binding.is_kinetic is False
