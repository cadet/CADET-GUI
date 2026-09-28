"""Generate the synthetic example data in examples/data/characterization/.

Each file is a real CADET-Process simulation of `CharacterizationWorkbenchWidget()`'s
default process with a few "true" parameters changed, sampled and noised. The true
values are listed in examples/data/characterization/README.md.

    python3 examples/generate_characterization_example_data.py
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np

warnings.filterwarnings("ignore")

from cadetgui.simulation import run_process  # noqa: E402
from cadetgui.widgets.composite import CharacterizationWorkbenchWidget  # noqa: E402

OUT_DIR = Path(__file__).parent / "data" / "characterization"
SIGNAL_UNIT, SIGNAL_PORT = "outlet", "inlet"

# Rapid-equilibrium SMA: the default binding model binds nothing.
_SMA = {"is_kinetic": False, "characteristic_charge": [5.0], "adsorption_rate": [2.0],
        "desorption_rate": [1.0]}

# file -> (noise scale, seed, {unit or "binding": {attribute: true value}})
DATASETS: dict[str, tuple[float, int, dict[str, dict[str, Any]]]] = {
    "periphery_pre_injection": (
        0.01, 20260924_01,
        {"tubing_pre_injection": {"length": 0.35, "axial_dispersion": [8e-7]}},
    ),
    "periphery_detectors": (
        0.01, 20260924_02,
        {"tubing_detectors": {"length": 0.22, "axial_dispersion": [5e-7]}},
    ),
    "pre_injection_mixer": (
        0.01, 20260924_03,
        {"tubing_pre_injection": {"length": 0.35}, "mixer": {"init_liquid_volume": 3e-6}},
    ),
    "bed_replicate_0": (
        0.015, 20260924_04, {"column": {"bed_porosity": 0.38, "axial_dispersion": [6e-8]}},
    ),
    "bed_replicate_1": (
        0.015, 20260924_05, {"column": {"bed_porosity": 0.38, "axial_dispersion": [6e-8]}},
    ),
    "particles": (0.015, 20260924_06, {"column": {"film_diffusion": [2e-5]}}),
    "adsorption": (0.015, 20260924_07, {"binding": {**_SMA, "capacity": 1200.0}}),
    "capacity": (0.015, 20260924_08, {"binding": {**_SMA, "capacity": 900.0}}),
}


def simulate(changes: dict[str, dict[str, Any]], *, scale: float, seed: int) -> tuple:
    """Return `(time_min, signal)` of the default process with `changes`, plus noise."""
    process = CharacterizationWorkbenchWidget().configuration.process
    for target, attributes in changes.items():
        flow_sheet = process.flow_sheet
        unit = flow_sheet.column.binding_model if target == "binding" else getattr(
            flow_sheet, target
        )
        for name, value in attributes.items():
            setattr(unit, name, value)

    solution = run_process(process).solution[SIGNAL_UNIT][SIGNAL_PORT]
    signal = solution.solution[:, 0].copy()
    rng = np.random.default_rng(seed)
    signal += rng.normal(0.0, scale * max(signal.max(), 1e-12), size=signal.shape)
    np.clip(signal, 0.0, None, out=signal)
    return solution.time / 60.0, signal


def main() -> None:
    """Write every dataset as a `time_min,signal` CSV."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (scale, seed, changes) in DATASETS.items():
        time_min, signal = simulate(changes, scale=scale, seed=seed)
        path = OUT_DIR / f"{name}.csv"
        with open(path, "w") as f:
            f.write("time_min,signal\n")
            f.writelines(f"{t:.6f},{s:.8f}\n" for t, s in zip(time_min, signal))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
