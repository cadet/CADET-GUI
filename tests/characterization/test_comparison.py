"""Comparison: a measured run against the simulation of its recipe."""
from __future__ import annotations

import json
from dataclasses import asdict, replace

import numpy as np
import pytest
from cadetgui.characterization.comparison import Comparison, recipe_from_dict
from cadetgui.characterization.parameter_store import ParameterStore

from characterization.synthetic import (
    LOOP_VOLUME,
    PRIOR,
    TRUTH,
    TUBING,
    akta_bytes,
    make_comparison,
    pulse_recipe,
    simulate_signal,
    store_with,
    synthetic_run,
)


@pytest.fixture(scope="module")
def comparison() -> Comparison:
    comparison = make_comparison()
    comparison.run = synthetic_run(comparison)
    return comparison


def centroid(time, values) -> float:
    return float(np.sum(time * values) / np.sum(values))


def test_json_round_trip_drops_the_run_and_reloads_it_from_the_data_file(comparison, tmp_path):
    raw = json.loads(json.dumps(comparison.to_dict()))
    assert "run" not in raw
    rebuilt = Comparison.from_dict(raw)
    assert rebuilt == comparison and rebuilt.run is None

    (tmp_path / comparison.data_file).write_bytes(akta_bytes(comparison.run))
    loaded = Comparison.from_dict(raw, base_dir=tmp_path)
    assert loaded.run.x_basis == "volume" and comparison.channel in loaded.run.channels
    assert any(text == "Phase Elution" for _, text in loaded.run.markers)

    standalone = replace(pulse_recipe(), instrument=None)
    assert recipe_from_dict(asdict(standalone)) == standalone


def test_build_process_applies_the_store_and_overrides():
    process = make_comparison(overrides={"cycle_time": 250.0}).build_process(store_with(TRUTH))
    assert process.name == "System pulse 1 (UV)"
    assert process.flow_sheet[TUBING].length == pytest.approx(0.8)
    assert process.cycle_time == pytest.approx(250.0)


@pytest.mark.parametrize("kwargs, flow_rate", [
    ({}, 1e-8),
    ({"overrides": {"flow_rate": 2e-8}}, 2e-8),
    ({"flow_rate": 3e-8}, 3e-8),
])
def test_resolved_flow_rate_prefers_the_run_then_overrides_then_recipe(kwargs, flow_rate):
    assert make_comparison(**kwargs).resolved_flow_rate == flow_rate


def test_reference_is_aligned_to_the_injection_and_normalized_by_area(comparison):
    process = comparison.build_process(store_with(TRUTH))
    reference = comparison.build_reference(process)
    sim_time, sim_values = simulate_signal(comparison)
    ref_values = np.asarray(reference.solution)[:, 0]
    assert 0.0 <= reference.time[0] and reference.time[-1] <= process.cycle_time
    assert centroid(reference.time, ref_values) == pytest.approx(
        centroid(sim_time, sim_values), abs=1.0
    )
    assert ref_values.max() == pytest.approx(1.0, rel=0.05)

    wrong = replace(comparison, injection_marker="Phase Sample")
    with pytest.raises(ValueError, match="Phase Elution"):
        wrong.build_reference(wrong.build_process(ParameterStore()))


def test_truth_scores_at_noise_level_and_the_prior_worse(comparison):
    at_truth = comparison.evaluate(store_with(TRUTH))
    at_prior = comparison.evaluate(store_with(PRIOR))
    assert at_truth.metric == "NRMSE" and at_truth.value < 0.02
    assert at_prior.value > 5 * at_truth.value
    assert at_truth.simulated_values.shape == at_truth.simulated_time.shape
    assert at_truth.reference_values.shape == at_truth.reference_time.shape


def test_measured_injection_aligns_a_time_axis_run():
    comparison = make_comparison(
        injection_marker=None, measured_injection=100.0, baseline_window=(0.0, 400.0),
    )
    comparison.run = synthetic_run(comparison, basis="time")
    assert comparison.evaluate(store_with(TRUTH)).value < 0.02


def test_total_concentration_sums_components():
    comparison = make_comparison(
        recipe=pulse_recipe(components=("A", "B")), components=None,
        normalization={"kind": "area", "target_area": 2 * LOOP_VOLUME},
    )
    comparison.run = synthetic_run(comparison)
    preview = comparison.evaluate(store_with(TRUTH))
    assert preview.simulated_values.max() == pytest.approx(2.0, rel=0.05)
    assert preview.value < 0.02


def test_problems(comparison):
    assert comparison.problems() == []
    assert any("No data loaded" in p for p in make_comparison().problems())
    broken = replace(
        comparison,
        channel="Cond",
        injection_marker="Phase Load",
        solution_path="tubing_detectors.outlet",
        components=["Salt"],
        recipe=replace(comparison.recipe, model_values={
            k: v for k, v in comparison.recipe.model_values.items() if k != "flow_rate"
        }),
    )
    text = "\n".join(broken.problems())
    for expected in ("Unknown channel 'Cond'", "Phase Load", "tubing_detectors.outlet",
                     "['Salt']", "flow rate is required"):
        assert expected in text
