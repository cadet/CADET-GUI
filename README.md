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

### The workbench

`WorkbenchWidget` is the top-level entry point — a sidebar with four steps
(System Configuration, Process Configuration, Simulation, Parameter
Estimation), each also reachable as its own attribute: `.instrument`,
`.configuration`, `.solution`, `.parameter_estimation`.

```python
from cadetgui.widgets.composite import WorkbenchWidget

workbench = WorkbenchWidget()
workbench.display()
```

See [`examples/workbench.ipynb`](examples/workbench.ipynb).

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
