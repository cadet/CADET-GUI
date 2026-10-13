# How CADET-GUI is built

A guide for developers new to this repository: what CADET-GUI is for, how the code is
organised, and where to start when you want to change or extend it. For installation and
usage see [README.md](README.md); for tests, linting and versioning see
[CONTRIBUTING.md](CONTRIBUTING.md).

## The idea

[CADET-Process](https://github.com/fau-advanced-separations/CADET-Process) models
chromatography processes in Python: component systems, unit operations, flow sheets,
processes with timed events, simulation, fitting and optimization. CADET-GUI adds widgets
on top of it, so that people can build, inspect and run these models in a Jupyter
notebook, or in a web page served by Voilà, without writing every line themselves.

Three ideas shape the whole package:

1. **CADET-Process does the work.** CADET-GUI never re-implements modelling, simulation
   or fitting. A widget creates, edits or shows CADET-Process objects and calls
   CADET-Process to run them.
2. **The objects stay yours.** Whatever a widget builds (a `FlowSheet`, a `Process`, a
   `SimulationResults`) is an ordinary CADET-Process object you can keep using in code.
   The GUI is a convenience, never a black box. Most widgets can also show the
   CADET-Process code that does what you just clicked ("Show code").
3. **Small widgets, composed.** Every capability is its own widget that works on its own
   in a notebook cell. Larger tools ("workbenches") are compositions of these widgets,
   not a separate application framework.

## Goals

- Make CADET-Process approachable: for teaching (one widget per concept, as used in the
  CADET workshop) and for lab scientists (guided workbenches in lab language).
- Cover a chromatography model-development workflow: set up an LC system and a method,
  simulate, compare with measured data, estimate and characterize model parameters.
- Let developers assemble their own tools from the same parts.
- Run unchanged in Jupyter, JupyterLab, VS Code notebooks and Voilà.

## Non-goals

- Replacing the CADET-Process Python API. Anything the GUI does not cover is done in code
  on the same objects.
- A second simulation or optimization engine, or copies of CADET-Process logic.
- A standalone desktop application or a JavaScript front-end framework. The front end is
  ipywidgets plus a few small hand-written JavaScript views; there is no build step.
- A general drag-and-drop flow-sheet editor (low priority; templates come first).
- Project management, versioning and multi-user storage (not decided yet).

## Two kinds of widgets

**Object widgets** each show or edit one CADET-Process object:
`ComponentSystemWidget`, `UnitOperationsWidget`, `FlowSheetWidget`, `ProcessWidget` and
`SimulationWidget`. You pass in your own objects and they edit them in place. They are
deliberately small and explain one concept each, which makes them suitable for teaching.

**Workbenches** combine many widgets into a guided tool with a sidebar:
- `InstrumentWorkbenchWidget`: pick an LC system (`CADETProcess.instruments`) and a
  process template, simulate it and fit parameters to measured data.
- `CharacterizationWorkbenchWidget`: a characterization study that adds measurements,
  fits model parameters step by step and keeps every accepted value with where it came
  from.

```python
from cadetgui import ProcessWidget, InstrumentWorkbenchWidget

ProcessWidget(process)            # one object, in a notebook cell
InstrumentWorkbenchWidget()       # a whole workbench
```

## How the code is organised

The package is split by **domain**, and each domain is named after the part of
CADET-Process it builds on. Code that does not need a user interface lives in
`cadetgui/<domain>/`; the widgets for that domain live in `cadetgui/widgets/<domain>/`.

```
cadetgui/
  process_model/      plain CADET-Process objects: parameter values, signals, simulation
  instrument/         LC systems and process templates (CADETProcess.instruments)
  estimation/         parameter estimation, optimizer runs, sensitivity
  characterization/   characterization studies: measurements, steps, parameter store
  parameters/         parameter metadata read from CADET-Process, form specifications
  io/                 files: measured data, saved configurations, simulation runs
  widgets/
    base.py           Widget, the base class of every composite widget
    ui/               shared building blocks: look, layout, HTML snippets, plots, sidebar
    elements/         basic inputs and charts (anywidget, with small JavaScript views)
    forms/            turns a form specification into input elements
    diagrams/         flow-sheet and LC-system diagrams (SVG)
    process_model/    object widgets
    instrument/       LC system, process configuration, simulation results, data import
    estimation/       parameter estimation
    characterization/ study setup, measurements, characterization steps, guide
    benches/          the two workbenches and the frame they share
```

Why this split:

- **Code without widgets is reusable and testable on its own.** Scripts, tests and other
  tools can use `cadetgui.instrument` or `cadetgui.characterization` without a notebook.
  These packages never import anything from `cadetgui.widgets`.
- **Mirrored names make code easy to find.** The widgets for `cadetgui/instrument/` are in
  `cadetgui/widgets/instrument/`.
- **Dependencies point one way.** Basic elements know nothing about forms; forms know
  nothing about domain widgets; workbenches may use everything, and nothing uses a
  workbench. Among the domains, `instrument` builds on `process_model`, and `estimation`
  and `characterization` build on `instrument`.

## How a widget is built

Composite widgets subclass `cadetgui.widgets.Widget`. A widget:

- builds its user interface in `self.root` (usually with `ui.layout.panel(...)`);
- takes its input in the constructor and in setter methods;
- returns what it built: `get_value()`, or attributes such as `.process` and `.results`;
- shows errors in its own status line instead of raising them silently;
- calls `self._notify(value)` after each accepted change, so others can react through
  `add_listener(fn)`.

Larger widgets are not one big class. They hold smaller parts, each with one job (a
section of a form, an editor, a chart with its picker), and talk to them through a few
public methods. Widgets connect to each other the same way, for example
`solution.bind_to_config(configuration)`, never by reaching into each other's internals.

At the bottom, inputs and charts in `widgets/elements/` are
[anywidget](https://anywidget.dev/) classes: one Python class with a few
[traitlets](https://traitlets.readthedocs.io/) plus a small JavaScript view. Everything
else is composed from standard [ipywidgets](https://ipywidgets.readthedocs.io/)
containers and these elements.

## A typical flow: configure and simulate

1. `InstrumentWidget` builds an `LCFlowSheet` (buffer inlets, mixer, sample loop, tubing,
   column, detectors) from your choices.
2. `ConfigurationWidget` takes that flow sheet, shows forms for the column, the binding
   model and a process template (for example Load–Wash–Elute) and builds a `Process`.
   Forms are generated from parameter metadata that CADET-Process itself provides, so
   units, bounds and descriptions are never typed in by hand.
3. `SolutionWidget` runs the process with CADET-Process and plots the chromatogram; runs
   are kept in a history and can be saved with the configuration that produced them.
4. The `Process` and `SimulationResults` stay available as plain objects.

The characterization workbench reuses steps 1–3 and adds a study around them: every
measurement keeps its own recipe (a saved configuration). Every fit starts from the
parameter values accepted in earlier steps.

## Where to start reading

| If you want to… | Start at |
|---|---|
| understand the shared kit | `cadetgui/widgets/base.py`, `cadetgui/widgets/ui/` |
| see a small, complete widget | `cadetgui/widgets/process_model/component_system.py` |
| see how forms come from CADET-Process | `cadetgui/parameters/`, `cadetgui/widgets/forms/` |
| follow the main workflow | `cadetgui/widgets/instrument/configuration.py`, `solution.py` |
| understand characterization | `cadetgui/characterization/study.py`, then `widgets/characterization/` |
| see how a workbench is assembled | `cadetgui/widgets/benches/instrument.py` |

The examples are the quickest way in:
`examples/process_model_widgets.ipynb` (object widgets), `examples/instrument_widgets.ipynb`
(widgets wired by hand), `examples/build_your_own_widget.ipynb`,
`examples/build_your_own_bench.ipynb` and the two workbench notebooks.

## Extending

- **A new widget:** put the logic that needs no user interface into the matching
  `cadetgui/<domain>/` package first, then subclass `Widget` in
  `cadetgui/widgets/<domain>/` and export it from that package's `__init__.py`. Build the
  layout from `cadetgui.widgets.ui` and the inputs from `cadetgui.widgets.elements`.
- **A new process template:** add it to `cadetgui/instrument/templates.py`; the
  configuration widget picks it up from there.
- **Your own workbench:** build and wire the widgets you need and hand them to
  `SidebarShell` (see `examples/build_your_own_bench.ipynb`).
- **A new input element:** a Python class in `widgets/elements/` plus its `.js` view;
  shared JavaScript and CSS pieces are in `widgets/elements/shared/`.

## Conventions

- Keep code lean; prefer composition over inheritance and small parts over big classes.
- One-line docstrings that say what something does. Comments only for constraints that are
  not obvious from the code, without history or dates.
- No module file names starting with `_`, and no importing another module's private
  (`_name`) functions. If two modules need a helper, make it public in one place.
- Do not add options or abstractions before something needs them.
- Validate at real boundaries (user input, CADET-Process bounds) and show the error in
  the widget.
- `ruff check cadetgui tests` must pass; tests live in `tests/`.

## Things that surprise newcomers

- After editing an element's `.js` or `.css`, restart the kernel; the files are read
  once when cadetgui is imported.
- Voilà and notebook execution need a kernel from the environment where cadetgui is
  installed, otherwise `import cadetgui` fails.
- A binding model must use the same `ComponentSystem` object as its column.
- Layout problems only show in a real browser; a clean Python run does not prove the
  page looks right.
