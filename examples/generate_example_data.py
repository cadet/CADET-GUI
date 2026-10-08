"""Generate the synthetic parameter-estimation examples `examples/data/example_*.csv`.

Every file is a CADET-Process simulation of the default configuration of
`ConfigurationWidget(instrument=InstrumentWidget())` (lab scale, Breakthrough template),
or of a named deviation from it, sampled at the column outlet with fixed-seed noise.
`example_lwe_signal.csv` instead starts from the standard SMA starting values with the
LWE template and adds detector tailing.

    python examples/generate_example_data.py

Deterministic (fixed seeds): re-running produces byte-identical files.
"""
from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

from cadetgui.io.configuration_store import ConfigurationState  # noqa: E402
from cadetgui.process_builder import build_process  # noqa: E402
from cadetgui.simulation import run_process  # noqa: E402
from cadetgui.widgets.composite import (  # noqa: E402
    ConfigurationWidget,
    InstrumentWidget,
)

OUT_DIR = Path(__file__).parent / "data"
EXTINCTION_COEFFICIENT = 100.0  # L/(mol·cm)
PATH_LENGTH = 0.2  # cm
LWE = "Load–Wash–Elute (LWE)"
SMA = "Steric Mass Action (SMA)"


def default_state() -> ConfigurationState:
    """Return the configuration a fresh `ConfigurationWidget` with an instrument starts with."""
    return ConfigurationWidget(instrument=InstrumentWidget()).snapshot()


def with_values(
    state: ConfigurationState, column: dict | None = None, binding: dict | None = None
) -> ConfigurationState:
    """Return `state` with some column and binding values replaced."""
    return dataclasses.replace(
        state,
        column_values={**state.column_values, **(column or {})},
        binding_values={**state.binding_values, **(binding or {})},
    )


def lwe_state() -> ConfigurationState:
    """Return the Salt + Protein LWE configuration with the standard SMA starting values."""
    configuration = ConfigurationWidget(instrument=InstrumentWidget())
    configuration.components = ["Salt", "Protein"]
    configuration.select_models(template=LWE, binding=SMA)
    return configuration.snapshot()


def outlet_signal(
    state: ConfigurationState,
    time_min: np.ndarray,
    component: int | None = None,
    tailing_s: float = 0.0,
) -> np.ndarray:
    """Simulate `state` and return the outlet concentration at `time_min`.

    `component` picks one component (default: the total); `tailing_s` passes the signal
    through a first-order lag with that time constant, like a detector flow cell.
    """
    solution = run_process(build_process(state)).solution["outlet"]["inlet"]
    time_s = np.asarray(solution.time)
    values = np.asarray(solution.solution).reshape(len(time_s), -1)
    signal = values.sum(axis=1) if component is None else values[:, component]
    if tailing_s > 0:
        lagged = np.empty_like(signal)
        lagged[0] = signal[0]
        decay = np.exp(-np.diff(time_s) / tailing_s)
        for i, d in enumerate(decay, start=1):
            lagged[i] = d * lagged[i - 1] + (1.0 - d) * signal[i]
        signal = lagged
    return np.interp(time_min * 60.0, time_s, signal)


def noisy(signal: np.ndarray, scale: float, seed: int) -> np.ndarray:
    """Add Gaussian noise of `scale` times the signal maximum, clipped at 0."""
    noise = np.random.default_rng(seed).normal(0.0, scale * signal.max(), signal.shape)
    return np.clip(signal + noise, 0.0, None)


def write_csv(name: str, header: str, time_min: np.ndarray, signal: np.ndarray) -> None:
    """Write a two-column CSV with the time in minutes."""
    lines = [header] + [f"{t:.2f},{s:.4f}" for t, s in zip(time_min, signal)]
    (OUT_DIR / name).write_text("\n".join(lines) + "\n")


def main() -> None:
    """Write the four example files."""
    base = default_state()
    time_min = np.round(np.arange(0.0, 5.0 + 1e-9, 0.01), 2)
    long_time_min = np.round(np.arange(0.0, 10.0 + 1e-9, 0.01), 2)

    uv = outlet_signal(base, time_min) * EXTINCTION_COEFFICIENT * PATH_LENGTH
    write_csv("example_uv_signal.csv", "time_min,UV280_mAU", time_min,
              noisy(uv, 0.01, 20260911))

    raw = outlet_signal(with_values(base, column={"total_porosity": 0.60}), time_min)
    write_csv("example_raw_signal.csv", "time_min,signal", time_min,
              noisy(raw, 0.015, 20260916))

    binding = with_values(
        base,
        column={"total_porosity": 0.65, "axial_dispersion": 2e-8},
        binding={"adsorption_rate": [0.3], "desorption_rate": [0.05]},
    )
    write_csv("example_binding_signal.csv", "time_min,signal", long_time_min,
              noisy(outlet_signal(binding, long_time_min), 0.01, 20260917))

    lwe = with_values(
        lwe_state(), binding={"adsorption_rate": [0.0, 12.0], "desorption_rate": [0.0, 60.0]}
    )
    lwe_time_min = np.round(np.arange(0.0, 25.0 + 1e-9, 0.01), 2)
    write_csv("example_lwe_signal.csv", "time_min,protein_mM", lwe_time_min,
              noisy(outlet_signal(lwe, lwe_time_min, component=1, tailing_s=4.0),
                    0.01, 20261007))


if __name__ == "__main__":
    main()
