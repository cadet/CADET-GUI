# CADET-GUI as a website

`app.ipynb` renders `ConfigurationWidget`, `SolutionWidget` (with its built-in
run history), and `ParameterEstimationWidget` — the same widgets used in
`examples/configuration_and_solution.ipynb` — composed into three tabs
(**Configuration** / **Solution** / **Parameter Estimation**), served via
[Voilà](https://voila.readthedocs.io/). Comparison against measured data lives
under **Parameter Estimation**, not alongside Solution — that's a deliberate
separation, not a demotion: the Solution tab shows only the raw simulation;
importing a dataset, calibrating it, and overlaying it against a simulated
signal is its own concern, with its own "Preview" step. Try uploading one of
the three example datasets in `examples/data/` (see `examples/EXAMPLE_DATA.md`
for exactly what configuration each was generated from, and what to check in
the parameter checklist) and clicking "Preview" to see it overlaid —
switching tabs doesn't lose anything; a plot rendered on one tab is still
there when you switch back.

## Run it

```bash
pip install voila  # one-time, not a cadetgui runtime dependency
voila examples/webapp/app.ipynb
```

Then open the URL Voilà prints (defaults to `http://localhost:8866`). What you
get is a plain web page — no notebook UI, no code, no cell boundaries, just a
header and three tabs. Anyone visiting the URL in a browser sees a website; the
`.ipynb` file is just this app's source format (convenient because it's also
directly editable/runnable in JupyterLab), not something end users interact
with.

## Why this proves anything

The widgets need a live Python backend regardless of deployment target — running
an actual CADET-Process/CADET-Core simulation can't happen client-side in a
browser. Voilà gives us that backend (one Jupyter kernel per visitor session) for
free, using the exact same widget-sync protocol our anywidget elements already
speak for Jupyter. So "the same widget code, unmodified, works in a notebook and
on a website" isn't a promise — `app.ipynb` and
`examples/configuration_and_solution.ipynb` import and use `ConfigurationWidget`/
`SolutionWidget` identically; only the composition/layout code differs.

## If you get `ModuleNotFoundError: No module named 'cadetgui'`

Voilà runs the notebook's cell(s) in a Jupyter **kernel**, which may not be the
same Python environment you're running `voila` from. Register a kernel for the
environment `cadetgui` is installed in (once):

```bash
python -m ipykernel install --user --name <env-name> --display-name "Python 3 (<env-name>)"
```

Then make sure the notebook's kernel metadata (`Kernel > Change Kernel` in
JupyterLab, or edit `metadata.kernelspec` in the `.ipynb` JSON) points at that
kernel name. Both notebooks in `examples/` are currently pinned to a kernel named
`cadet_dev` — rename to match your own environment if it's called something else.
