from __future__ import annotations

import numpy as np
import pytest
from cadetgui.sensitivity import (
    _get_by_path,
    _report_from_matrix,
    _set_by_path,
    analyze_sensitivity,
    perturb_parameters,
    response_matrix,
)
from cadetgui.widgets.composite import ConfigurationWidget, InstrumentWidget


class _FakeSolution:
    def __init__(self, values):
        self.solution = np.asarray(values)


class _FakeResult:
    def __init__(self, values):
        self.solution = {"outlet": {"outlet": _FakeSolution(values)}}


def _fake_perturbed(responses: dict[str, np.ndarray]) -> dict:
    """Build a `perturb_parameters`-shaped dict with a hand-chosen response
    vector per parameter, bypassing real simulation entirely -- the response
    for path `p` is exactly `(value_plus - value_minus) * responses[p]`, so
    with `value_plus - value_minus == 1.0` the resulting `response_matrix`
    row is exactly `responses[p]`."""
    return {
        path: (_FakeResult(-vector / 2), _FakeResult(vector / 2), -0.5, 0.5)
        for path, vector in responses.items()
    }


def test_response_matrix_reads_the_signal_path_and_normalizes_by_the_step():
    perturbed = _fake_perturbed({"a": np.array([1.0, 2.0, 3.0])})

    matrix = response_matrix(perturbed, ("outlet", "outlet"))

    assert matrix.shape == (1, 3)
    np.testing.assert_allclose(matrix[0], [1.0, 2.0, 3.0])


def test_identical_response_vectors_are_flagged_as_a_correlated_pair():
    vector = np.array([1.0, 2.0, 3.0, 0.5])
    orthogonal = np.array([0.0, 1.0, 0.0, -1.0])
    perturbed = _fake_perturbed({"a": vector, "b": 2.0 * vector, "c": orthogonal})
    matrix = response_matrix(perturbed, ("outlet", "outlet"))

    report = _report_from_matrix(["a", "b", "c"], matrix, similarity_threshold=0.99)

    assert report.cosine_similarity[0, 1] == pytest.approx(1.0, abs=1e-9)
    assert report.flagged_pairs == [("a", "b", pytest.approx(1.0, abs=1e-9))]


def test_orthogonal_response_vectors_are_not_flagged():
    perturbed = _fake_perturbed({"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])})
    matrix = response_matrix(perturbed, ("outlet", "outlet"))

    report = _report_from_matrix(["a", "b"], matrix, similarity_threshold=0.99)

    assert report.cosine_similarity[0, 1] == pytest.approx(0.0, abs=1e-9)
    assert report.flagged_pairs == []


def test_get_and_set_by_path_round_trip_a_list_wrapped_scalar():
    class Unit:
        axial_dispersion = [1e-8]

    unit = Unit()
    assert _get_by_path(unit, "axial_dispersion") == pytest.approx(1e-8)

    _set_by_path(unit, "axial_dispersion", 2e-8)

    assert unit.axial_dispersion == [2e-8]


def _built_process():
    iw = InstrumentWidget()
    cw = ConfigurationWidget(instrument=iw)
    return cw.process


@pytest.mark.slow
def test_analyze_sensitivity_runs_end_to_end_against_a_real_process():
    process = _built_process()

    report = analyze_sensitivity(
        process,
        ["flow_sheet.column.total_porosity", "flow_sheet.column.axial_dispersion"],
        ("outlet", "outlet"),
        relative_step=1e-2,
    )

    assert report.parameter_names == [
        "flow_sheet.column.total_porosity", "flow_sheet.column.axial_dispersion",
    ]
    assert report.cosine_similarity.shape == (2, 2)
    assert report.cosine_similarity[0, 0] == pytest.approx(1.0, abs=1e-6)
    assert report.condition_number > 0
    for a, b, score in report.flagged_pairs:
        assert -1.0 <= score <= 1.0


@pytest.mark.slow
def test_perturb_parameters_never_mutates_the_caller_s_process():
    process = _built_process()
    original_value = process.flow_sheet.column.total_porosity

    perturb_parameters(process, ["flow_sheet.column.total_porosity"], relative_step=1e-2)

    assert process.flow_sheet.column.total_porosity == original_value
