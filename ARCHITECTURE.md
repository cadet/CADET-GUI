# CADET-GUI architecture

Orientation for developers and tools working on this repository. Usage: [README.md](README.md).
Tests, lint, versioning: [CONTRIBUTING.md](CONTRIBUTING.md).

## Product

- **What:** a chromatography model-development workbench powered by CADET-Process.
- **Not:** a GUI that mirrors the CADET-Process object hierarchy. Scientific tasks lead;
  CADET-Process objects are the result, not the interface.
- **Stack:** scientist → GUI workflow layer → model/instrument templates
  (`CADETProcess.instruments`, `modelBuilder`, `characterization`) → CADET-Process → CADET-Core.
- **Form:** independently usable notebook widgets; workbenches are compositions of them.
  Same code in Jupyter, JupyterLab, VS Code notebooks and Voilà.

## Goals

| Goal | Meaning |
|---|---|
| Workflow first | Navigation and terms follow how chromatography scientists work: instrument, column, transport and binding characterization; comparison with experiments; estimation; validation; simulation; design-space exploration and optimization. |
| Templates before primitives | Standard work starts from LC-system and process templates, not an empty flow sheet. |
| No Python for standard work | Users do not create unit operations, connections, events or parameter paths by hand. |
| Progressive disclosure | Required scientific inputs first; optional, numerical and implementation settings on demand. |
| Expert escape hatch | Every widget exposes the underlying CADET-Process objects, parameter paths and the equivalent Python ("Show code"). |
| Backend fidelity | Every GUI configuration maps unambiguously to standard CADET-Process objects; generated code reproduces the GUI result. |
| No duplicated engine | Simulation, model building, comparison, characterization and optimization are CADET-Process calls. |
| Reusability | Instruments, columns, methods, models and datasets are reusable across experiments; widgets are reusable across workbenches. |
| Traceability | Results stay linked to the data, model, parameters, template, settings and backend versions that produced them; accepted values keep their provenance. |
| Extensibility | New templates, models, workflows and widgets are added without redesigning the shell; developers compose their own tools from the same widgets. |
| Teaching | Object widgets explain one CADET-Process concept each (CADET workshop). |

## Non-goals

| Non-goal | Instead |
|---|---|
| Replacing the CADET-Process Python API | Users continue in code on the same objects. |
| A second numerical engine or GUI-owned copies of CADET-Process logic | Call CADET-Process; report missing features upstream. |
| Direct use of unstable CADET-Process branch APIs from widgets | Go through the headless domain packages; detect and report backend capability. |
| A generic drag-and-drop flow-sheet editor before the template workflows are complete | Templates and object widgets. |
| A standalone desktop app, JS framework or JS build step | ipywidgets + small anywidget views; Voilà for web pages. |
| GxP compliance: authentication, authorization, e-signatures, audit trails | Out of scope until decided separately; the data model keeps provenance and versions. |
| Mid-run control of running simulations | Rerun with changed inputs. |

## Open decisions

- Project storage format and lifecycle (case save/load, result export, widget registration).
- CADET-Process release baseline (development targets `dev`).
- Hosting of the Voilà deployment.

## Layout

Rule: code without a user interface in `cadetgui/<domain>/`; its widgets in
`cadetgui/widgets/<domain>/`. Domains are named after the CADET-Process module they build on.

| Path | Contents |
|---|---|
| `cadetgui/process_model/` | parameter values, signal positions, simulation of any `Process` |
| `cadetgui/instrument/` | LC-system tables, process templates, recipes, `process_builder`, starting values |
| `cadetgui/estimation/` | parameter estimation, optimizer runs, sensitivity |
| `cadetgui/characterization/` | `Study`, `ParameterStore`, `Comparison`, runner, stages, step checks, `guide/` |
| `cadetgui/parameters/` | parameter metadata read from CADET-Process, `FieldSpec`/`ModelSpec` |
| `cadetgui/io/` | configuration store, run store, experimental data |
| `cadetgui/widgets/base.py` | `Widget` base class |
| `cadetgui/widgets/ui/` | theme, layout (`panel`, `section`, `row`, `note`, `collapsible`, `CodeView`), HTML snippets, formatting, plotting, `SidebarShell` |
| `cadetgui/widgets/elements/` | anywidget inputs and charts (Python class + `.js`), `shared/` JS/CSS |
| `cadetgui/widgets/forms/` | `FormRenderer`: `ModelSpec` → elements → built object |
| `cadetgui/widgets/diagrams/` | SVG diagrams of flow sheets and LC systems |
| `cadetgui/widgets/process_model/` | object widgets: `ComponentSystemWidget`, `UnitOperationsWidget`, `FlowSheetWidget`, `ProcessWidget`, `SimulationWidget` |
| `cadetgui/widgets/instrument/` | `InstrumentWidget`, `ConfigurationWidget`, `SolutionWidget`, `RunHistoryWidget`, `DataImportWidget` |
| `cadetgui/widgets/estimation/` | `ParameterEstimationWidget` |
| `cadetgui/widgets/characterization/` | study setup, components, `measurements/`, `step/`, parameter store, guide |
| `cadetgui/widgets/benches/` | `InstrumentWorkbenchWidget`, `CharacterizationWorkbenchWidget`, shared frame |
| `examples/` | notebooks, one per entry point (see table below) |
| `tests/` | pytest suite |

Public imports: `cadetgui` (workbenches, object widgets), `cadetgui.widgets` (`Widget`, layout
helpers, `SidebarShell`), `cadetgui.widgets.<domain>`, `cadetgui.<domain>`.

## Dependency rules

- `cadetgui/<domain>/` never imports `cadetgui.widgets`, ipywidgets or anywidget.
- `elements` → no `forms`; `forms` → no domain widgets; `ui`, `diagrams` → no domain widgets.
- Domain order: `process_model` < `instrument` < `estimation`, `characterization` < `benches`.
  Exception: `process_model` widgets use `instrument` for `LCFlowSheet` extras (template mode,
  phase spans).
- Nothing imports `benches`.
- No module file starts with `_`; no import of another module's `_private` names.
- Widgets connect only through public methods (`bind_to_*`, `add_listener`,
  `snapshot`/`apply_state`), never through each other's private attributes.

## Widget contract

| Aspect | Implementation |
|---|---|
| base | subclass `cadetgui.widgets.Widget`; UI in `self.root`; renders as last cell expression or via `display()` |
| input | constructor arguments, setters |
| output | `get_value()` or attributes (`.process`, `.flow_sheet`, `.results`) holding plain CADET-Process objects |
| events | `add_listener(fn)`; widget calls `self._notify(value)` after each accepted change |
| validation | errors shown in the widget's status line; last valid build kept |
| code | `code()` + `CodeView` ("Show code") where a widget builds something |
| structure | composite widgets hold single-purpose parts (sections, editors, views) |

Elements: `value`, `validate`, `error`, `units`; values that are not JSON-safe stay
server-side (`ChoiceField` syncs labels + index).

## Entry points

| Task | Start |
|---|---|
| shared kit | `cadetgui/widgets/base.py`, `cadetgui/widgets/ui/` |
| smallest complete widget | `cadetgui/widgets/process_model/component_system.py` |
| forms from CADET-Process metadata | `cadetgui/parameters/`, `cadetgui/widgets/forms/` |
| main workflow | `cadetgui/widgets/instrument/configuration.py`, `solution.py` |
| characterization | `cadetgui/characterization/study.py`, `cadetgui/widgets/characterization/` |
| workbench assembly | `cadetgui/widgets/benches/instrument.py` |
| examples | `examples/process_model_widgets.ipynb`, `instrument_widgets.ipynb`, `build_your_own_widget.ipynb`, `build_your_own_bench.ipynb`, `instrument_workbench.ipynb`, `characterization.ipynb` |

## Extending

| Add | Where |
|---|---|
| widget | headless logic in `cadetgui/<domain>/`; `Widget` subclass in `cadetgui/widgets/<domain>/`; export in the package `__init__.py` |
| process template | `cadetgui/instrument/templates.py` (`INSTRUMENT_TEMPLATES`) |
| workbench | build + wire widgets, pass `(label, widget.root)` to `SidebarShell`, frame with `bench_root` |
| input element | class in `cadetgui/widgets/elements/` + `.js` view; shared parts in `elements/shared/` |

## Conventions

- Lean code; composition over inheritance; no option or abstraction without a caller.
- One-line docstrings; comments only for non-obvious constraints, no history.
- Validate at real boundaries (user input, CADET-Process bounds); no silent `except`.
- `ruff check cadetgui tests` clean.

## Gotchas

- Element `.js`/`.css` are read at import: restart the kernel after editing them.
- Voilà/notebook execution needs a kernel of the environment cadetgui is installed in.
- A binding model must share its column's `ComponentSystem` object.
- Layout problems only show in a real browser.
