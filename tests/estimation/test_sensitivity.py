"""Local sensitivity: correlated pairs, perturbation steps, a real process."""
from __future__ import annotations

from types import SimpleNamespace

import cadetgui.estimation.sensitivity as sensitivity
import numpy as np
import pytest
from cadetgui.estimation.sensitivity import analyze_sensitivity, perturb_parameters

SHAPE_A = np.array([1.0, 2.0, 3.0, 0.5])
SHAPE_C = np.array([2.0, -1.0, 0.0, 0.0])


@pytest.fixture
def linear_model(monkeypatch):
    """A fake process whose outlet signal is (a + 2 b) * SHAPE_A + c * SHAPE_C."""
    def simulate(process):
        signal = (process.a + 2 * process.b[0]) * SHAPE_A + process.c * SHAPE_C
        port = SimpleNamespace(solution=signal)
        return SimpleNamespace(solution={"outlet": {"outlet": port}})

    monkeypatch.setattr(sensitivity, "run_process", simulate)
    return SimpleNamespace(a=1.0, b=[0.0], c=2.0)


def test_parallel_responses_are_flagged_and_orthogonal_ones_are_not(linear_model):
    report = analyze_sensitivity(linear_model, ["a", "b", "c"], ("outlet", "outlet"))

    assert report.parameter_names == ["a", "b", "c"]
    assert report.cosine_similarity[0, 1] == pytest.approx(1.0)
    assert report.cosine_similarity[0, 2] == pytest.approx(0.0, abs=1e-9)
    assert report.flagged_pairs == [("a", "b", pytest.approx(1.0))]
    assert report.condition_number > 1e6


@pytest.mark.parametrize(("path", "base"), [("a", 1.0), ("b", 0.0)])
def test_steps_are_relative_or_absolute_at_zero_and_the_process_is_untouched(
    linear_model, path, base
):
    ((_, _, minus, plus),) = perturb_parameters(
        linear_model, [path], relative_step=1e-2
    ).values()

    assert (minus, plus) == pytest.approx((base - 1e-2, base + 1e-2))
    assert (linear_model.a, linear_model.b) == (1.0, [0.0])


def test_a_multi_component_parameter_is_rejected(linear_model):
    linear_model.b = [0.0, 1.0]

    with pytest.raises(ValueError, match="single scalar"):
        perturb_parameters(linear_model, ["b"])


def test_report_for_a_real_process(pulse_process):
    paths = ["flow_sheet.column.total_porosity", "flow_sheet.column.axial_dispersion"]

    report = analyze_sensitivity(pulse_process, paths, ("outlet", "inlet"), relative_step=1e-2)

    assert report.cosine_similarity.shape == (2, 2)
    assert report.cosine_similarity[0, 0] == pytest.approx(1.0)
    assert report.condition_number > 0
    assert pulse_process.flow_sheet.column.total_porosity == 0.7
