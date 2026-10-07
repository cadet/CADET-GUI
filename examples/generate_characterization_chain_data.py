"""Generate a synthetic two-step characterization chain, shaped like Äkta/Unicorn exports.

Step 1 ("Extra-column volume", `CharacterizeTubing`) fits `tubing_pre_column`'s length and
axial dispersion from two replicate pulse-tracer runs with the column bypassed. Step 2
("Column packing", `CharacterizeBed`) fits the column's bed porosity, particle
porosity and axial dispersion from two small-tracer and two large-tracer pulse runs with
the column in line, carrying step 1's fitted tubing forward.
Every "true" value is invented for this synthetic instrument, and every measured
CSV is a real CADET-Process simulation reshaped into Äkta form (volume axis, per-channel
sampling, detector units, fixed-seed noise) rather than anything recorded by an instrument.

    python3 examples/generate_characterization_chain_data.py

Deterministic (fixed seeds): re-running produces byte-identical files.
"""
from __future__ import annotations

import csv
import json
import re
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

warnings.filterwarnings("ignore")

from cadetgui.characterization_guide import (  # noqa: E402
    CHAIN_BY_ID,
    LARGE_TRACER,
    SMALL_TRACER,
    SYSTEM_TRACER,
)
from cadetgui.configuration_store import (  # noqa: E402
    ConfigurationState,
    InstrumentState,
)
from cadetgui.parameter_store import (  # noqa: E402
    ParameterSpec,
    ParameterStore,
    Provenance,
    apply_store,
)
from cadetgui.process_builder import build_process  # noqa: E402
from CADETProcess.simulator import Cadet  # noqa: E402

OUT_DIR = Path(__file__).parent / "data" / "characterization_akta"
STEP1_NAME = CHAIN_BY_ID["system_periphery"].title
STEP2_NAME = CHAIN_BY_ID["column_packing"].title

# %% Physical constants -- all invented for this synthetic instrument.

FLOW_RATE = 8.3e-9           # m^3/s, shared by every run
LOOP_VOLUME = 20e-9          # m^3, sample loop
LOOP_DIAMETER = 0.75e-3      # m
C_SAMPLE = 50.0              # mol/m^3, tracer concentration in the sample loop
TARGET_AREA = C_SAMPLE * LOOP_VOLUME   # mol, injected amount (flow-weighted integral)

TUBING_PRE_COLUMN_DIAMETER = 0.8e-3         # m, known (not fitted)
TUBING_PRE_COLUMN_LENGTH = 0.42             # m, step-1 truth
TUBING_PRE_COLUMN_AXIAL_DISPERSION = 4.5e-7  # m^2/s, step-1 truth
CYCLE_TIME_TUBING = 150.0  # s

COLUMN_DIAMETER = 5e-3        # m, known
COLUMN_LENGTH = 0.02          # m, known
PARTICLE_RADIUS = 3.0e-5      # m, known
BED_POROSITY = 0.36           # step-2 truth
PARTICLE_POROSITY = 0.68      # step-2 truth
COLUMN_AXIAL_DISPERSION = 5.5e-8   # m^2/s, step-2 truth
SMALL_TRACER_FILM_DIFFUSION = 8e-5  # m/s, known
LARGE_TRACER_FILM_DIFFUSION = 0.0   # m/s, known -- pore-excluded (200 nm vs. a 60 µm bead)

TUBING_DETECTORS_DIAMETER = 0.5e-3  # m, known -- small detector-to-detector volume
TUBING_DETECTORS_LENGTH = 0.05      # m, known
CYCLE_TIME_BED = 300.0  # s

# The measured export starts this many seconds before the aligned (t=0) injection: the
# Pulse Injection template has no pre-injection equilibration phase to simulate, so this
# dead time exists only in the "measured" clock, recovered by the injection marker.
PRE_OFFSET_S = 60.0

PATHS = {
    "tubing_pre_column_diameter": "flow_sheet.tubing_pre_column.diameter",
    "tubing_pre_column_length": "flow_sheet.tubing_pre_column.length",
    "tubing_pre_column_axial_dispersion": "flow_sheet.tubing_pre_column.axial_dispersion",
    "tubing_detectors_diameter": "flow_sheet.tubing_detectors.diameter",
    "tubing_detectors_length": "flow_sheet.tubing_detectors.length",
    "tubing_detectors_axial_dispersion": "flow_sheet.tubing_detectors.axial_dispersion",
    "column_particle_radius": "flow_sheet.column.particle_radius",
    "column_film_diffusion": "flow_sheet.column.film_diffusion",
    "column_bed_porosity": "flow_sheet.column.bed_porosity",
    "column_particle_porosity": "flow_sheet.column.particle_porosity",
    "column_axial_dispersion": "flow_sheet.column.axial_dispersion",
}
_SPECIES_INDEXED = {"tubing_pre_column_axial_dispersion", "tubing_detectors_axial_dispersion",
                     "column_film_diffusion", "column_axial_dispersion"}
SPECS: dict[str, ParameterSpec] = {
    path: ParameterSpec(path, species_indexed=key in _SPECIES_INDEXED)
    for key, path in PATHS.items()
}

STEP1_TRUTH = {
    PATHS["tubing_pre_column_length"]: TUBING_PRE_COLUMN_LENGTH,
    PATHS["tubing_pre_column_axial_dispersion"]: TUBING_PRE_COLUMN_AXIAL_DISPERSION,
}
STEP2_TRUTH = {
    PATHS["column_bed_porosity"]: BED_POROSITY,
    PATHS["column_particle_porosity"]: PARTICLE_POROSITY,
    PATHS["column_axial_dispersion"]: COLUMN_AXIAL_DISPERSION,
}


# %% Parameter store chain (initial -> step 1 -> step 2)


def initial_store() -> ParameterStore:
    """Known hardware values, fitted by neither step."""
    return ParameterStore(specs=SPECS).updated(
        {
            PATHS["tubing_pre_column_diameter"]: TUBING_PRE_COLUMN_DIAMETER,
            PATHS["tubing_detectors_diameter"]: TUBING_DETECTORS_DIAMETER,
            PATHS["tubing_detectors_length"]: TUBING_DETECTORS_LENGTH,
            PATHS["column_particle_radius"]: PARTICLE_RADIUS,
            PATHS["column_film_diffusion"]: {
                "SmallTracer": SMALL_TRACER_FILM_DIFFUSION,
                "LargeTracer": LARGE_TRACER_FILM_DIFFUSION,
            },
        },
        Provenance(step="initial", note="known hardware, not determined by either step"),
    )


def step1_store(prior: ParameterStore) -> ParameterStore:
    """Prior plus the extra-column volume truth, probed by `SystemTracer`."""
    return prior.updated(
        {
            PATHS["tubing_pre_column_length"]: TUBING_PRE_COLUMN_LENGTH,
            PATHS["tubing_pre_column_axial_dispersion"]: {
                "SystemTracer": TUBING_PRE_COLUMN_AXIAL_DISPERSION,
            },
        },
        Provenance(
            step=STEP1_NAME,
            probe="SystemTracer",
            source="System pulse 1 (UV), System pulse 2 (UV)",
        ),
    )


def step2_store(step1: ParameterStore) -> ParameterStore:
    """Step 1's store, its periphery re-keyed to the C-run species, plus the bed truth.

    Mirrors `CharacterizeColumnVoidVolume`'s own chain handoff: the periphery dispersion
    fitted with one probe is carried to the others unchanged (a modelling assumption, not
    a second measurement), and `tubing_detectors` reuses it at the same flow rate.
    """
    dispersion = step1.value(PATHS["tubing_pre_column_axial_dispersion"], species="SystemTracer")
    carried = step1.updated(
        {
            PATHS["tubing_pre_column_axial_dispersion"]: {
                "SmallTracer": dispersion, "LargeTracer": dispersion,
            },
            PATHS["tubing_detectors_axial_dispersion"]: {"SmallTracer": dispersion},
        },
        Provenance(
            step=STEP1_NAME,
            probe="SystemTracer",
            source="System pulse 1 (UV), System pulse 2 (UV)",
            note="reused for the C-run species and the detector tubing at the same flow rate",
        ),
    )
    return carried.updated(
        {
            PATHS["column_bed_porosity"]: BED_POROSITY,
            PATHS["column_particle_porosity"]: PARTICLE_POROSITY,
            PATHS["column_axial_dispersion"]: {
                "SmallTracer": COLUMN_AXIAL_DISPERSION, "LargeTracer": COLUMN_AXIAL_DISPERSION,
            },
        },
        Provenance(
            step=STEP2_NAME,
            probe="SmallTracer, LargeTracer",
            source=(
                "Small tracer pulse 1 (conductivity), Small tracer pulse 2 (conductivity), "
                "Large tracer pulse 1 (UV), Large tracer pulse 2 (UV)"
            ),
        ),
    )


# %% Recipes


def _instrument(bypass: Sequence[str]) -> InstrumentState:
    return InstrumentState(
        include_sample_loop=True,
        sample_loop_volume=LOOP_VOLUME,
        sample_loop_diameter_auto=False,
        sample_loop_diameter=LOOP_DIAMETER,
        bypass_units=list(bypass),
    )


def tubing_recipe(species: str) -> ConfigurationState:
    """System pulses: pulse tracer with the column and every other periphery segment bypassed."""
    return ConfigurationState(
        components=[species],
        column_key="Lumped Rate Model With Pores (LRMP)",
        binding_key="None",
        template_key="Pulse Injection",
        instrument=_instrument(
            ["tubing_pre_injection", "column", "tubing_post_column", "tubing_detectors"]
        ),
        model_values={
            "c_buffer_a": [0.0], "c_sample": [C_SAMPLE],
            "cycle_time": CYCLE_TIME_TUBING, "flow_rate": FLOW_RATE,
        },
    )


def bed_recipe(species: str, tracer: str) -> ConfigurationState:
    """C-*: pulse tracer with the column in line; `tracer` is `"small"` or `"large"`.

    Column values are placeholders (`apply_store` overwrites bed/particle porosity, axial
    dispersion and film diffusion); geometry (diameter, length) is the recipe's own, not
    the store's, since which column is in the flow path is part of a run's identity, not
    a fitted or looked-up value.
    """
    bypass = ["tubing_pre_injection", "tubing_post_column"]
    if tracer == "large":
        bypass.append("tubing_detectors")
    return ConfigurationState(
        components=[species],
        column_key="Lumped Rate Model With Pores (LRMP)",
        binding_key="None",
        template_key="Pulse Injection",
        instrument=_instrument(bypass),
        column_values={
            "diameter": COLUMN_DIAMETER, "length": COLUMN_LENGTH,
            "particle_radius": 1.0e-5, "bed_porosity": 0.5, "particle_porosity": 0.5,
            "axial_dispersion": 1e-8, "film_diffusion": 1e-4,
        },
        model_values={
            "c_buffer_a": [0.0], "c_sample": [C_SAMPLE],
            "cycle_time": CYCLE_TIME_BED, "flow_rate": FLOW_RATE,
        },
    )


# %% Simulation


def simulate_clean(
    recipe: ConfigurationState, store: ParameterStore, solution_path: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Build `recipe`, apply `store`, simulate, and return `(time_s, concentration)`.

    `solution_path` is `"<unit>.outlet"`; the process carries exactly one species, so
    only its own (sole) component is returned. Discretization is left at its default
    (not coarsened): `cadetgui.comparison.Comparison.build_process` simulates the same
    recipe at the default resolution, and the two must agree for a fit against this data
    to recover the truth rather than a numerical-dispersion artifact.
    """
    process = build_process(recipe)
    apply_store(process, store)
    results = Cadet().simulate(process)
    unit, _, port = solution_path.partition(".")
    solution = getattr(getattr(results.solution, unit), port)
    return np.asarray(solution.time), np.asarray(solution.solution[:, 0])


# %% Äkta/Unicorn shaping


def _time_grid(total_s: float, dt: float) -> np.ndarray:
    return np.arange(int(round(total_s / dt)) + 1) * dt


def _shape_channel(
    t_meas: np.ndarray,
    true_time: np.ndarray,
    true_signal: np.ndarray,
    *,
    baseline: float,
    response: float,
    noise_sigma: float,
    seed: int,
    drift: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> np.ndarray:
    """Detector trace on the measured clock: baseline + response * concentration + noise.

    `t_meas` is seconds on the measured clock (injection at `PRE_OFFSET_S`); concentration
    outside the simulated domain (before injection, or after the cycle ends) is zero.
    """
    t_sim = t_meas - PRE_OFFSET_S
    concentration = np.interp(t_sim, true_time, true_signal, left=0.0, right=0.0)
    signal = baseline + response * concentration
    if drift is not None:
        signal = signal + drift(t_meas)
    rng = np.random.default_rng(seed)
    return signal + rng.normal(0.0, noise_sigma, size=signal.shape)


def _to_ml(time_s: "float | np.ndarray") -> np.ndarray:
    return np.asarray(time_s) * FLOW_RATE * 1e6


def _cell(values: Sequence[float], i: int, fmt: str = "{:.6f}") -> str:
    return fmt.format(values[i]) if i < len(values) else ""


def write_akta_csv(
    path: Path,
    uv: tuple[np.ndarray, np.ndarray],
    cond: tuple[np.ndarray, np.ndarray],
    markers: list[tuple[float, str]],
) -> None:
    """Write a 3-header-row Äkta/Unicorn-style export: UV 1_280, Cond, Run Log."""
    uv_v, uv_s = _to_ml(uv[0]), uv[1]
    cond_v, cond_s = _to_ml(cond[0]), cond[1]
    log_v = [m[0] for m in markers]
    log_t = [m[1] for m in markers]
    n_rows = max(len(uv_v), len(cond_v), len(log_v))

    rows = [
        ["Chromatogram", "", "", "", "", ""],
        ["UV 1_280", "", "Cond", "", "Run Log", ""],
        ["ml", "mAU", "ml", "mS/cm", "ml", ""],
    ]
    for i in range(n_rows):
        rows.append([
            _cell(uv_v, i), _cell(uv_s, i),
            _cell(cond_v, i), _cell(cond_s, i),
            _cell(log_v, i), (log_t[i] if i < len(log_t) else ""),
        ])

    with open(path, "w", newline="") as handle:
        csv.writer(handle).writerows(rows)


# %% Detector calibration -- arbitrary response factors and baselines.

UV_BASELINE, UV_RESPONSE, UV_NOISE = 4.0, 6.0, 0.5         # mAU, mAU / (mol/m^3), mAU
COND_BASELINE, COND_RESPONSE, COND_NOISE = 42.0, 0.15, 0.004  # mS/cm, mS/cm / (mol/m^3), mS/cm

UV_DT, COND_DT = 0.5, 0.2  # s -- channels sampled at different rates


# `cadetgui.characterization_guide.EXPERIMENT_TYPES` ids, per `RunSpec.tracer`.
EXPERIMENT_TYPE_IDS = {
    "system": "system_pulse",
    "small": "column_pulse_small_tracer",
    "large": "column_pulse_large_tracer",
}


@dataclass(frozen=True)
class RunSpec:
    """One measured run: its recipe, truth store, detector channel and shaping seed."""

    name: str
    species: str
    tracer: str  # "system", "small", "large"
    recipe: ConfigurationState
    store: ParameterStore
    solution_path: str
    channel: str  # informative channel: "UV 1_280" or "Cond"
    cycle_time: float
    seed: int
    drift: bool = False


def _drift(seed: int) -> Callable[[np.ndarray], np.ndarray]:
    """Pre-injection valve-transition artifact: a sharp, narrow dip early in the export.

    Narrow enough that its own contribution to the whole-trace area-normalization
    integral is small next to the tracer peak's, but deep enough to dominate the
    default (no explicit window) whole-trace baseline threshold, which picks the
    lowest ~2.5% of points: this is what makes the default baseline wrong and an
    explicit post-peak `baseline_window` necessary.
    """
    def _f(t_meas: np.ndarray) -> np.ndarray:
        return -2.0 * np.exp(-0.5 * ((t_meas - 5.0) / 0.4) ** 2)
    return _f


def generate_run(run: RunSpec) -> dict:
    """Simulate, shape and write one run's CSV; return its comparison dict."""
    true_time, true_signal = simulate_clean(run.recipe, run.store, run.solution_path)

    total_s = PRE_OFFSET_S + run.cycle_time
    t_uv = _time_grid(total_s, UV_DT)
    t_cond = _time_grid(total_s, COND_DT)

    uv_is_informative = run.channel == "UV 1_280"
    uv_signal = _shape_channel(
        t_uv, true_time, true_signal,
        baseline=UV_BASELINE, response=UV_RESPONSE if uv_is_informative else 0.0,
        noise_sigma=UV_NOISE, seed=run.seed,
        drift=_drift(run.seed) if (run.drift and uv_is_informative) else None,
    )
    cond_signal = _shape_channel(
        t_cond, true_time, true_signal,
        baseline=COND_BASELINE, response=COND_RESPONSE if not uv_is_informative else 0.0,
        noise_sigma=COND_NOISE, seed=run.seed + 1,
        drift=_drift(run.seed) if (run.drift and not uv_is_informative) else None,
    )

    markers = [
        (0.0, "Phase Equilibration"),
        (float(_to_ml(PRE_OFFSET_S)), "Phase Elution"),
        (float(_to_ml(0.85 * total_s)), "Phase Wash"),
    ]
    write_akta_csv(
        OUT_DIR / f"{_file_stem(run.name)}.csv", (t_uv, uv_signal), (t_cond, cond_signal), markers
    )

    baseline_window = None
    if run.drift:
        # Wide, stable post-peak window: far enough past the peak to be flat, far
        # enough from the run end to hold many points (a narrow window lets a linear
        # baseline fit's slope noise blow up once extrapolated across the whole run).
        window_s = (PRE_OFFSET_S + 0.35 * run.cycle_time, PRE_OFFSET_S + 0.95 * run.cycle_time)
        baseline_window = (float(_to_ml(window_s[0])), float(_to_ml(window_s[1])))

    comparison = {
        "name": run.name,
        "data_file": f"{_file_stem(run.name)}.csv",
        "channel": run.channel,
        "flow_rate": None,
        "recipe": asdict(run.recipe),
        "overrides": {},
        "injection_marker": "Phase Elution",
        "measured_injection": None,
        "baseline_window": list(baseline_window) if baseline_window is not None else None,
        "normalization": {"kind": "area", "target_area": TARGET_AREA},
        "solution_path": run.solution_path,
        "components": [run.species],
        "metric": "NRMSE",
        "window": [None, None],
        "probe": run.species,
        "experiment_type": EXPERIMENT_TYPE_IDS[run.tracer],
    }
    return comparison


# %% Manifest assembly


def _file_stem(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def build_runs() -> list[RunSpec]:
    """Return the six runs: two system pulses (step 1), small and large tracer pulses (step 2)."""
    s1 = step1_store(initial_store())
    s2 = step2_store(s1)

    return [
        RunSpec(
            "System pulse 1 (UV)", "SystemTracer", "system", tubing_recipe("SystemTracer"), s1,
            "tubing_pre_column.outlet", "UV 1_280", CYCLE_TIME_TUBING, seed=20260928_01,
        ),
        RunSpec(
            "System pulse 2 (UV)", "SystemTracer", "system", tubing_recipe("SystemTracer"), s1,
            "tubing_pre_column.outlet", "UV 1_280", CYCLE_TIME_TUBING, seed=20260928_02,
        ),
        RunSpec(
            "Small tracer pulse 1 (conductivity)", "SmallTracer", "small",
            bed_recipe("SmallTracer", "small"), s2,
            "tubing_detectors.outlet", "Cond", CYCLE_TIME_BED, seed=20260928_03, drift=True,
        ),
        RunSpec(
            "Small tracer pulse 2 (conductivity)", "SmallTracer", "small",
            bed_recipe("SmallTracer", "small"), s2,
            "tubing_detectors.outlet", "Cond", CYCLE_TIME_BED, seed=20260928_04,
        ),
        RunSpec(
            "Large tracer pulse 1 (UV)", "LargeTracer", "large",
            bed_recipe("LargeTracer", "large"), s2,
            "column.outlet", "UV 1_280", CYCLE_TIME_BED, seed=20260928_05,
        ),
        RunSpec(
            "Large tracer pulse 2 (UV)", "LargeTracer", "large",
            bed_recipe("LargeTracer", "large"), s2,
            "column.outlet", "UV 1_280", CYCLE_TIME_BED, seed=20260928_06,
        ),
    ]


def build_manifest() -> dict:
    """Simulate and write every run's CSV, and return the manifest dict written beside them."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = build_runs()
    comparisons = [generate_run(run) for run in runs]

    return {
        "description": (
            "Synthetic two-step characterization chain (extra-column volume, then column "
            "packing), shaped like Äkta/Unicorn exports. Every number is invented "
            "for this synthetic instrument."
        ),
        "initial_store": initial_store().to_dict(),
        "steps": [
            {
                "name": STEP1_NAME,
                "stage": "tubing",
                "options": {"tubing": "tubing_pre_column"},
                "comparisons": ["System pulse 1 (UV)", "System pulse 2 (UV)"],
                "bounds": {
                    "tubing_pre_column_length": [0.1, 1.0],
                    "tubing_pre_column_axial_dispersion": [1e-8, 1e-5],
                },
                "frozen": [],
                "truth": STEP1_TRUTH,
            },
            {
                "name": STEP2_NAME,
                "stage": "bed",
                "options": {"include_particle_porosity": True},
                "comparisons": [
                    "Small tracer pulse 1 (conductivity)",
                    "Small tracer pulse 2 (conductivity)",
                    "Large tracer pulse 1 (UV)",
                    "Large tracer pulse 2 (UV)",
                ],
                "bounds": {
                    "bed_porosity": [0.25, 0.5],
                    "particle_porosity": [0.55, 0.85],
                    "axial_dispersion": [1e-9, 1e-6],
                },
                "frozen": [],
                "truth": STEP2_TRUTH,
            },
        ],
        "comparisons": comparisons,
        "components": [
            {"name": "SystemTracer", "role": SYSTEM_TRACER},
            {"name": "SmallTracer", "role": SMALL_TRACER},
            {"name": "LargeTracer", "role": LARGE_TRACER},
        ],
    }


def main() -> None:
    """Write every CSV and `manifest.json` to `OUT_DIR`."""
    manifest = build_manifest()
    path = OUT_DIR / "manifest.json"
    with open(path, "w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"wrote {path} and {len(manifest['comparisons'])} CSVs to {OUT_DIR}")


if __name__ == "__main__":
    main()
