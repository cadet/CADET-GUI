"""Synthetic measurements for characterization tests: simulated, shifted, scaled, noisy."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
from cadetgui.characterization.comparison import Comparison
from cadetgui.characterization.parameter_store import (
    ParameterSpec,
    ParameterStore,
    Provenance,
)
from cadetgui.io.configuration_store import ConfigurationState, InstrumentState
from cadetgui.io.experimental_data import Channel, ExperimentalRun
from cadetgui.process_model.simulation import run_process

DATA_DIR = Path(__file__).parents[2] / "examples" / "data" / "characterization_akta"
MANIFEST = DATA_DIR / "manifest.json"

TUBING = "tubing_pre_column"
LENGTH = f"flow_sheet.{TUBING}.length"
DISPERSION = f"flow_sheet.{TUBING}.axial_dispersion"
FILM = "flow_sheet.column.film_diffusion"
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


def data_bytes(file_name: str) -> bytes:
    """Bytes of an example data file."""
    return (DATA_DIR / file_name).read_bytes()


def store_with(values: dict) -> ParameterStore:
    return ParameterStore(specs=SPECS).updated(values, Provenance(step="test"))


def pulse_recipe(components=("SmallTracer",)) -> ConfigurationState:
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
            "cycle_time": 400.0, "flow_rate": FLOW_RATE,
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
        normalization={"kind": "area", "target_area": LOOP_VOLUME},
        components=["SmallTracer"],
        probe="SmallTracer",
    )
    return Comparison(**{**defaults, **kwargs})


def simulate_signal(comparison: Comparison, values: dict = TRUTH):
    """Simulated total outlet concentration at `values`, on the process clock."""
    process = comparison.build_process(store_with(values))
    solution = run_process(process).solution_cycles[TUBING]["outlet"][-1]
    return np.asarray(solution.time), np.asarray(solution.solution).sum(axis=1)


def synthetic_run(
    comparison: Comparison, values: dict = TRUTH, *, injection_s: float = 100.0,
    seed: int = 0, basis: str = "volume",
) -> ExperimentalRun:
    """The truth trace delayed by `injection_s`, scaled, drifting and noisy."""
    sim_time, sim_values = simulate_signal(comparison, values)
    time = np.arange(0.0, injection_s + sim_time[-1], 1.0)
    concentration = np.interp(time - injection_s, sim_time, sim_values, left=0.0, right=0.0)
    rng = np.random.default_rng(seed)
    signal = 50.0 * concentration + 3.0 + 1e-3 * time + rng.normal(0, 0.02, time.size)
    channel = comparison.channel
    if basis == "time":
        return ExperimentalRun(comparison.name, {channel: Channel(channel, time, signal)},
                               "time", "s")
    ml_per_s = comparison.resolved_flow_rate * 1e6
    return ExperimentalRun(
        comparison.name, {channel: Channel(channel, time * ml_per_s, signal)}, "volume", "mL",
        markers=[(0.0, "Phase Equilibration"), (injection_s * ml_per_s, "Phase Elution")],
    )


def akta_bytes(run: ExperimentalRun) -> bytes:
    """A volume-axis run as an Äkta/Unicorn-style export (3 header rows)."""
    (channel,) = run.channels.values()
    rows = [["Run", "", "Run", ""], [channel.name, "", "Run Log", ""], ["mL", "mAU", "mL", ""]]
    for i, (x, v) in enumerate(zip(channel.x, channel.values)):
        marker = run.markers[i] if i < len(run.markers) else ("", "")
        rows.append([repr(float(x)), repr(float(v)), str(marker[0]), marker[1]])
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode()
