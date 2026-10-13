# CADET-GUI

Widget-based graphical elements to configure, run and analyse
[CADET-Process](https://github.com/fau-advanced-separations/CADET-Process)
simulations from a Jupyter notebook.

---

## Authors

* Hannah Lanzrath
* Johannes Schmölder

---

## Installation

Not yet published on PyPI. Install from source into an environment that
already has [CADET-Process](https://github.com/fau-advanced-separations/CADET-Process)
and a CADET-Core build set up:

```bash
git clone git@github.com:cadet/CADET-GUI.git
cd CADET-GUI
pip install -e .
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for running the test suite, linting
and versioning.

---

## Getting started

Everything is a plain [ipywidgets](https://ipywidgets.readthedocs.io/)/
[anywidget](https://anywidget.dev/) object: build one, call `.display()`, and
keep using its Python attributes from other cells.

### Import layers

| Import from | What it holds |
| --- | --- |
| `cadetgui` | the ready-made benches (`InstrumentWorkbenchWidget`, `CharacterizationWorkbenchWidget`) and one widget per CADET-Process object (`ComponentSystemWidget`, `UnitOperationsWidget`, `FlowSheetWidget`, `ProcessWidget`, `SimulationWidget`) |
| `cadetgui.widgets.process_model` | widgets for plain `CADETProcess.processModel` objects, and their parts (`EventEditor`, `PolynomialEditor`, ...) |
| `cadetgui.widgets.instrument` | LC system, process configuration from a template, simulation results, data import |
| `cadetgui.widgets.estimation` | parameter estimation |
| `cadetgui.widgets.characterization` | characterization study: setup, measurements, steps, parameters, guide |
| `cadetgui.widgets.elements` | atomic input controls and charts |
| `cadetgui.widgets` | `Widget` (base class), layout helpers and the bench kit (`SidebarShell`, `bench_root`, ...) |
| `cadetgui.process_model`, `cadetgui.instrument`, `cadetgui.estimation`, `cadetgui.characterization` | the same domains without widgets |
| `cadetgui.io` | file I/O: measured data, saved configurations, simulation runs |

### The workbench

`InstrumentWorkbenchWidget` is a sidebar with four steps (System Configuration, Process
Configuration, Simulation, Parameter Estimation), each also reachable as its
own attribute: `.instrument`, `.configuration`, `.solution`,
`.parameter_estimation`.

```python
from cadetgui import InstrumentWorkbenchWidget

workbench = InstrumentWorkbenchWidget()
workbench.display()
```

See [`examples/instrument_workbench.ipynb`](examples/instrument_workbench.ipynb).
Standard starting values (`cadetgui/instrument/starting_values.json`) are filled
into freshly chosen models; the "Use standard starting values" checkbox in the
process configuration, or `InstrumentWorkbenchWidget(starting_values=False)`, turns that off.

### The characterization workbench

`CharacterizationWorkbenchWidget` walks a study from the system and its
measurements through step-by-step parameter fits.

```python
from cadetgui import CharacterizationWorkbenchWidget

CharacterizationWorkbenchWidget().display()
```

See [`examples/characterization.ipynb`](examples/characterization.ipynb).

### Composing widgets yourself

Build and wire the same widgets by hand for a custom layout or a subset of
steps:

```python
from cadetgui.widgets.instrument import ConfigurationWidget, SolutionWidget

config = ConfigurationWidget()
solution = SolutionWidget()
solution.bind_to_config(config)

config.display()
solution.display()
```

To frame your own selection as a bench, hand `(label, widget)` panes to
`cadetgui.widgets.SidebarShell` and wrap it with `cadetgui.widgets.bench_root`.

See [`examples/instrument_widgets.ipynb`](examples/instrument_widgets.ipynb)
and [`examples/build_your_own_bench.ipynb`](examples/build_your_own_bench.ipynb).

### Example data

[`examples/data/`](examples/data/) and
[`examples/EXAMPLE_DATA.md`](examples/EXAMPLE_DATA.md) hold small synthetic
datasets for exercising Parameter Estimation without your own experimental
files.

### Running as a web app

[`examples/webapp/`](examples/webapp/) deploys the instrument, configuration,
simulation and parameter-estimation widgets as a standalone tabbed page via
[Voilà](https://voila.readthedocs.io/):

```bash
pip install voila
voila examples/webapp/app.ipynb
```

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).
