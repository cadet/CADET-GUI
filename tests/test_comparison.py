from __future__ import annotations

import csv
import io
import json
import warnings
from dataclasses import asdict, replace

import numpy as np
import pytest
from cadetgui.comparison import Comparison, recipe_from_dict
from cadetgui.configuration_store import ConfigurationState, InstrumentState
from cadetgui.experimental_data import Channel, ExperimentalRun
from cadetgui.parameter_store import ParameterSpec, ParameterStore, Provenance
from cadetgui.simulation import run_process

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

TUBING = "tubing_pre_column"
LENGTH = f"flow_sheet.{TUBING}.length"
DISPERSION = f"flow_sheet.{TUBING}.axial_dispersion"
SPECS = {
    LENGTH: ParameterSpec(LENGTH),
    DISPERSION: ParameterSpec(DISPERSION, species_indexed=True),
}

FLOW_RATE = 1e-8
LOOP_VOLUME = 1e-7
TRUE_DISPERSION = 2e-6
SPECIES = ("SmallTracer", "A", "B")
TRUTH = {LENGTH: 0.8, DISPERSION: dict.fromkeys(SPECIES, TRUE_DISPERSION)}
PRIOR = {LENGTH: 0.4, DISPERSION: dict.fromkeys(SPECIES, TRUE_DISPERSION)}
SIGNAL_SCALE = 50.0


def store_with(values: dict) -> ParameterStore:
    return ParameterStore(specs=SPECS).updated(values, Provenance(step="test"))


def pulse_recipe(components=("SmallTracer",), flow_rate=FLOW_RATE) -> ConfigurationState:
    """Pulse through `tubing_pre_column` only; other periphery units and the column bypassed."""
    n = len(components)
    return ConfigurationState(
        components=list(components),
        column_key="Lumped Rate Model Without Pores (LRM)",
        binding_key="None",
        template_key="Pulse Injection",
        instrument=InstrumentState(
            include_sample_loop=True,
            sample_loop_volume=LOOP_VOLUME,
            bypass_units=[
                "mixer", "tubing_pre_injection", "column", "tubing_post_column",
                "tubing_detectors",
            ],
            unit_values={TUBING: {"diameter": 0.5e-3, "length": 0.1, "axial_dispersion": 1e-7}},
        ),
        model_values={
            "c_sample": [1.0] * n, "c_buffer_a": [0.0] * n,
            "cycle_time": 400.0, "flow_rate": flow_rate,
        },
    )


def make_comparison(name="System pulse 1 (UV)", **kwargs) -> Comparison:
    defaults = dict(
        name=name,
        data_file=f"{name}.csv",
        channel="UV 1_280",
        recipe=pulse_recipe(),
        solution_path=f"{TUBING}.outlet",
        injection_marker="Phase Elution",
        baseline_window=(0.0, 4.0),
        normalization={"kind": "area", "target_area": LOOP_VOLUME * 1.0},
        components=["SmallTracer"],
        probe="SmallTracer",
    )
    return Comparison(**{**defaults, **kwargs})


def simulate_signal(comparison: Comparison, values: dict) -> tuple[np.ndarray, np.ndarray]:
    """Simulated total outlet concentration at `values`, on the process clock."""
    process = comparison.build_process(store_with(values))
    solution = run_process(process).solution_cycles[TUBING]["outlet"][-1]
    return np.asarray(solution.time), np.asarray(solution.solution).sum(axis=1)


def synthetic_run(
    comparison: Comparison,
    values: dict = TRUTH,
    *,
    injection_s: float = 100.0,
    noise: float = 0.02,
    seed: int = 0,
    basis: str = "volume",
) -> ExperimentalRun:
    """A measured run: the truth trace delayed by `injection_s`, scaled, drifting, noisy."""
    sim_time, sim_values = simulate_signal(comparison, values)
    flow_rate = comparison.resolved_flow_rate
    time = np.arange(0.0, injection_s + sim_time[-1], 1.0)
    concentration = np.interp(time - injection_s, sim_time, sim_values, left=0.0, right=0.0)
    rng = np.random.default_rng(seed)
    signal = SIGNAL_SCALE * concentration + 3.0 + 1e-3 * time + rng.normal(0, noise, time.size)
    if basis == "time":
        return ExperimentalRun(
            comparison.name, {comparison.channel: Channel(comparison.channel, time, signal)},
            "time", "s",
        )
    volume = time * flow_rate * 1e6
    injection_ml = injection_s * flow_rate * 1e6
    return ExperimentalRun(
        comparison.name,
        {comparison.channel: Channel(comparison.channel, volume, signal)},
        "volume", "mL",
        markers=[(0.0, "Phase Equilibration"), (injection_ml, "Phase Elution")],
    )


def akta_bytes(run: ExperimentalRun) -> bytes:
    """Serialize a volume-axis run as an Äkta/Unicorn-style export (3 header rows)."""
    (channel,) = run.channels.values()
    rows = [
        ["Run", "", "Run", ""],
        [channel.name, "", "Run Log", ""],
        ["mL", "mAU", "mL", ""],
    ]
    for i, (x, v) in enumerate(zip(channel.x, channel.values)):
        marker = run.markers[i] if i < len(run.markers) else ("", "")
        rows.append([repr(float(x)), repr(float(v)), str(marker[0]), marker[1]])
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode()


def _centroid(time: np.ndarray, values: np.ndarray) -> float:
    return float(np.sum(time * values) / np.sum(values))


@pytest.fixture(scope="module")
def comparison() -> Comparison:
    comparison = make_comparison()
    comparison.run = synthetic_run(comparison)
    return comparison


class TestSerialization:
    def test_round_trip_through_json_drops_the_run(self, comparison):
        raw = json.loads(json.dumps(comparison.to_dict()))
        assert "run" not in raw
        rebuilt = Comparison.from_dict(raw)
        assert rebuilt == comparison
        assert rebuilt.run is None
        assert rebuilt.recipe == comparison.recipe

    def test_to_dict_has_exactly_the_schema_fields(self, comparison):
        assert set(comparison.to_dict()) == {
            "name", "data_file", "channel", "flow_rate", "recipe", "overrides",
            "injection_marker", "measured_injection", "baseline_window", "normalization",
            "solution_path", "components", "metric", "window", "probe",
            "experiment_type",
        }

    def test_from_dict_with_base_dir_loads_the_data_file(self, comparison, tmp_path):
        (tmp_path / comparison.data_file).write_bytes(akta_bytes(comparison.run))
        loaded = Comparison.from_dict(comparison.to_dict(), base_dir=tmp_path)
        assert loaded.run.x_basis == "volume"
        assert comparison.channel in loaded.run.channels
        assert any(text == "Phase Elution" for _, text in loaded.run.markers)

    def test_recipe_from_dict_handles_a_standalone_recipe(self):
        state = replace(pulse_recipe(), instrument=None)
        assert recipe_from_dict(asdict(state)) == state


class TestBuildProcess:
    def test_names_the_process_and_applies_the_store(self, comparison):
        process = comparison.build_process(store_with(TRUTH))
        assert process.name == "System pulse 1 (UV)"
        assert process.flow_sheet[TUBING].length == pytest.approx(0.8)

    def test_overrides_reach_the_template(self):
        comparison = make_comparison(overrides={"cycle_time": 250.0})
        assert comparison.build_process(ParameterStore()).cycle_time == pytest.approx(250.0)

    def test_flow_rate_falls_back_to_overrides_then_recipe(self):
        assert make_comparison().resolved_flow_rate == FLOW_RATE
        assert make_comparison(overrides={"flow_rate": 2e-8}).resolved_flow_rate == 2e-8
        assert make_comparison(flow_rate=3e-8).resolved_flow_rate == 3e-8


class TestReference:
    def test_injection_is_aligned_to_the_simulated_injection(self, comparison):
        process = comparison.build_process(store_with(TRUTH))
        reference = comparison.build_reference(process)
        sim_time, sim_values = simulate_signal(comparison, TRUTH)
        ref_values = np.asarray(reference.solution)[:, 0]
        assert reference.time[0] >= 0.0
        assert reference.time[-1] <= process.cycle_time
        assert _centroid(reference.time, ref_values) == pytest.approx(
            _centroid(sim_time, sim_values), abs=1.0
        )

    def test_area_normalization_matches_the_injected_amount(self, comparison):
        reference = comparison.build_reference(comparison.build_process(store_with(TRUTH)))
        assert np.asarray(reference.solution).max() == pytest.approx(1.0, rel=0.05)

    def test_wrong_marker_raises_with_the_available_markers(self, comparison):
        wrong = replace(comparison, injection_marker="Phase Sample")
        with pytest.raises(ValueError, match="Phase Elution"):
            wrong.build_reference(wrong.build_process(ParameterStore()))

    def test_measured_injection_aligns_a_time_axis_run(self):
        comparison = make_comparison(
            injection_marker=None, measured_injection=100.0, baseline_window=(0.0, 400.0),
        )
        comparison.run = synthetic_run(comparison, basis="time")
        assert comparison.evaluate(store_with(TRUTH)).value < 0.02


class TestEvaluate:
    def test_truth_scores_at_noise_level_and_the_prior_scores_worse(self, comparison):
        at_truth = comparison.evaluate(store_with(TRUTH))
        at_prior = comparison.evaluate(store_with(PRIOR))
        assert at_truth.metric == "NRMSE"
        assert at_truth.value < 0.02
        assert at_prior.value > 5 * at_truth.value

    def test_preview_carries_both_traces(self, comparison):
        preview = comparison.evaluate(store_with(TRUTH))
        assert preview.name == "System pulse 1 (UV)"
        assert preview.simulated_values.shape == preview.simulated_time.shape
        assert preview.reference_values.shape == preview.reference_time.shape
        assert preview.simulated_values.max() == pytest.approx(1.0, rel=0.05)

    def test_total_concentration_sums_components(self):
        recipe = pulse_recipe(components=("A", "B"))
        comparison = make_comparison(
            recipe=recipe, components=None,
            normalization={"kind": "area", "target_area": 2 * LOOP_VOLUME},
        )
        comparison.run = synthetic_run(comparison)
        preview = comparison.evaluate(store_with(TRUTH))
        assert preview.simulated_values.max() == pytest.approx(2.0, rel=0.05)
        assert preview.value < 0.02


class TestProblems:
    def test_valid_comparison_has_none(self, comparison):
        assert comparison.problems() == []

    def test_reports_each_problem(self, comparison):
        broken = replace(
            comparison,
            channel="Cond",
            injection_marker="Phase Load",
            solution_path="tubing_detectors.outlet",
            components=["Salt"],
            recipe=replace(
                comparison.recipe,
                model_values={
                    k: v for k, v in comparison.recipe.model_values.items() if k != "flow_rate"
                },
            ),
        )
        text = "\n".join(broken.problems())
        assert "Unknown channel 'Cond'" in text
        assert "Phase Load" in text
        assert "tubing_detectors.outlet" in text
        assert "['Salt']" in text
        assert "flow rate is required" in text

    def test_reports_a_missing_run(self):
        assert any("No data loaded" in p for p in make_comparison().problems())
