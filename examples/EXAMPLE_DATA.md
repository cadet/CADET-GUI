# Example datasets

The `example_*.csv` files in `examples/data/` are *synthetic*: each one is the
outlet signal of a real CADET-Process simulation of the base configuration
below (or a named deviation from it), sampled and given a small amount of
fixed-seed noise. None of it is measured data. Knowing how each file was made
tells you the "correct" answer before you fit it, so you can check that
parameter estimation actually recovers it.

They are written by `examples/generate_example_data.py` (run it from the
repository root; re-running produces identical files).

The base is the default configuration of
`ConfigurationWidget(instrument=InstrumentWidget())` (and of the simulation
workbench), so the files fit out of the box without entering any values:
lab-scale `LumpedRateModelWithoutPores` column, `length = 0.05` m,
`diameter = 0.005` m, `total_porosity = 0.75`, `axial_dispersion = 1e-8`,
non-binding `Linear` isotherm (`adsorption_rate = desorption_rate = [0]`),
1 component, **Breakthrough** template with feed concentration `10` mol/m³,
flow rate 1 mL/min (`1.667e-8` m³/s) and cycle time `600` s, all instrument
units bypassed. Each row below only lists what was changed from that base.

| File | Changed from the base | Signal / Calibration | Window | Noise (seed) |
|---|---|---|---|---|
| `example_uv_signal.csv` | *(nothing, the base itself)* | Outlet, Beer-Lambert (`extinction_coefficient = 100` L/(mol·cm), `path_length = 0.2` cm) | 0–5 min, 0.01 min steps | Gaussian, 1 % of max, seed `20260911` |
| `example_raw_signal.csv` | `total_porosity = 0.60` | Outlet, no calibration | 0–5 min, 0.01 min steps | Gaussian, 1.5 % of max, seed `20260916` |
| `example_binding_signal.csv` | `total_porosity = 0.65`, `axial_dispersion = 2e-8`, `adsorption_rate = [0.3]`, `desorption_rate = [0.05]` | Outlet, no calibration | 0–10 min, 0.01 min steps | Gaussian, 1 % of max, seed `20260917` |

All noise is clipped at `0` afterward (no negative signal values). Every file
has a two-column header with the time in minutes (`time_min,...`) and reads
directly with `DataImportWidget`.

## `example_uv_signal.csv`

The Beer-Lambert calibration exercise: the process is the base configuration
unchanged, only the *signal* is transformed
(`signal = concentration * extinction_coefficient * path_length`) to mimic a
raw UV280 detector trace. Pick **Calibration: Beer-Lambert**, enter
`extinction_coefficient = 100`, `path_length = 0.2`, and the trace lines up
with the simulated breakthrough curve. Not meant for fitting (nothing was
perturbed to fit *towards*).

## `example_raw_signal.csv`

The simplest fitting exercise: only `total_porosity` differs from the base
(`0.60` vs. `0.75`), so the breakthrough front arrives earlier. Pick
**Calibration: None**, add only **Total porosity**, run; Nelder-Mead from the
base value recovers `0.6001`.

## `example_binding_signal.csv`

A retained solute: `total_porosity`, `axial_dispersion` and the linear binding
rates differ from the base, so the breakthrough front is delayed to about
2.5 min and broadened by the binding kinetics. No calibration.

Verified with Nelder-Mead, starting from `total_porosity = 0.5`,
`adsorption_rate = 0.1`, `desorption_rate = 0.1` and leaving
`axial_dispersion` at the base value:

| Parameter | True value | Recovered |
|---|---|---|
| `total_porosity` | 0.65 | 0.642 |
| `adsorption_rate` | 0.3 | 0.295 |
| `desorption_rate` | 0.05 | 0.0501 |

`axial_dispersion` (true `2e-8`) is not in that verified set: on a single
noisy trace its broadening of the front overlaps with that of the binding
kinetics, so add it only once the other three are fitted.
