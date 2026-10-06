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
| `cadetgui` | the ready-made benches: `WorkbenchWidget`, `CharacterizationWorkbenchWidget` |
| `cadetgui.widgets.composite` | task widgets (configuration, simulation, measurements, steps, ...) |
| `cadetgui.widgets.elements` | atomic input controls and charts |
| `cadetgui.widgets` | the bench kit (`SidebarShell`, `bench_root`, `resolve_step`, `validate_steps`, `collect_panes`, `system_pane_label`, `SYSTEM_GROUP`) and HTML helpers (`status_html`, `term_html`, `info_box_html`, `checklist_html`, `style_tag`) |
| `cadetgui.characterization` | headless characterization core: `Study`, `Comparison`, `ParameterStore`, step setups and fits |
| `cadetgui.io` | file I/O: measured data, saved configurations, simulation runs |

### The workbench

`WorkbenchWidget` is a sidebar with four steps (System Configuration, Process
Configuration, Simulation, Parameter Estimation), each also reachable as its
own attribute: `.instrument`, `.configuration`, `.solution`,
`.parameter_estimation`.

```python
from cadetgui import WorkbenchWidget

workbench = WorkbenchWidget()
workbench.display()
```

See [`examples/workbench.ipynb`](examples/workbench.ipynb).

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
from cadetgui.widgets.composite import ConfigurationWidget, SolutionWidget

config = ConfigurationWidget()
solution = SolutionWidget()
solution.bind_to_config(config)

config.display()
solution.display()
```

To frame your own selection as a bench, hand `(label, widget)` panes to
`cadetgui.widgets.SidebarShell` and wrap it with `cadetgui.widgets.bench_root`.

See [`examples/configuration_and_solution.ipynb`](examples/configuration_and_solution.ipynb)
and [`examples/custom_sidebar.ipynb`](examples/custom_sidebar.ipynb).

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
