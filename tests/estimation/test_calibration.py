"""Calibrating a measured signal: Beer-Lambert, area normalization, invalid input."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from cadetgui.estimation.parameter_estimation import (
    build_reference,
    calibrate_reference,
)
from cadetgui.widgets.estimation import ReferenceSignalControls

T = np.linspace(0, 10, 50)
PEAK = 10.0 * np.exp(-((T - 5) ** 2))


@pytest.fixture
def reference():
    return build_reference("uv", T, PEAK, component_name="B")


def test_no_calibration_returns_the_reference_itself(reference):
    assert calibrate_reference(reference, "none") is reference


def test_beer_lambert_divides_by_extinction_times_path_length(reference):
    calibrated = calibrate_reference(
        reference, "beer_lambert", extinction_coefficient=2.0, path_length=5.0
    )

    np.testing.assert_allclose(calibrated.solution[:, 0], PEAK / 10.0)
    assert calibrated.component_system.names == ["B"]


def test_area_normalization_matches_the_target_area(reference):
    calibrated = calibrate_reference(reference, "normalize_area", target_area=3.0)

    assert calibrated.fraction_mass()[0] == pytest.approx(3.0)
    assert calibrated.component_system.names == ["B"]


def test_an_unknown_method_is_rejected(reference):
    with pytest.raises(ValueError):
        calibrate_reference(reference, "not_a_method")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("method", "fields", "error"),
    [
        ("none", {}, None),
        ("beer_lambert", {"extinction_field": 2.0, "path_length_field": 1.0}, None),
        ("beer_lambert", {"extinction_field": 0.0}, "extinction"),
        ("beer_lambert", {"path_length_field": -1.0}, "path length"),
        ("normalize_area", {"target_area_field": 2.0}, None),
        ("normalize_area", {"target_area_field": 0.0}, "injected amount"),
    ],
)
def test_controls_validate_and_apply_the_chosen_calibration(method, fields, error):
    controls = ReferenceSignalControls()
    controls.refresh_component_options(["A", "B"])
    controls.calibration_picker.value = method
    for name, value in fields.items():
        getattr(controls, name).value = value

    message = controls.calibration_error()

    if error is not None:
        assert error in message.lower()
        return
    assert message is None
    calibrated = controls.reference_for(SimpleNamespace(label="run", time_min=T, signal=PEAK))
    assert calibrated.component_system.names == ["A"]
    assert calibrated.time[-1] == pytest.approx(600.0)
