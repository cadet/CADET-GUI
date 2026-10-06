from __future__ import annotations

import dataclasses
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, List, Optional

import ipywidgets as W

from ...cadetprocessadapter import UNIT_LABELS
from ...characterization.guide import EXPERIMENT_TYPES
from ...characterization.parameter_store import (
    ChainError,
    ParameterSpec,
    ParameterStore,
    check_chain,
    missing_requirements,
)
from ...characterization.study import Study
from .._chrome import style_tag
from .._help import term_html
from .._status import status_html
from ..elements import ChoiceField, SelectableTable

__all__ = ["ParameterStoreWidget", "parameter_label", "set_by_label"]

CURRENT = "__current__"
INITIAL = "__initial__"
ASSUMED = "assumed: "


def parameter_label(path: str) -> str:
    """Plain name for a parameter path, e.g. "Tubing (pre column) · axial dispersion"."""
    parts = path.split(".")
    if len(parts) >= 3 and parts[0] == "flow_sheet" and parts[1] in UNIT_LABELS:
        return f"{UNIT_LABELS[parts[1]]} · {' '.join(parts[2:]).replace('_', ' ')}"
    return path


def set_by_label(step: str) -> str:
    """Plain "Set by" text for a provenance step; implied values name their experiment type."""
    if not step.startswith(ASSUMED):
        return step
    type_id = step[len(ASSUMED):]
    experiment = EXPERIMENT_TYPES.get(type_id)
    return f"Assumed by experiment type: {experiment.label if experiment else type_id}"


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def _metric(metric: Optional[dict]) -> str:
    return ", ".join(f"{k} {_fmt(v)}" for k, v in (metric or {}).items())


def chain_warnings(study: Study) -> List[str]:
    """Return chain-order problems of `study.steps`, and requirements unmet by accepted stores."""
    warnings: List[str] = []
    steps = []
    for setup in study.steps:
        try:
            steps.append(setup.step)
        except ValueError as exc:
            warnings.append(f"Step {setup.name!r} is incomplete: {exc}")
    paths = {p for step in steps for p in (*step.requires, *step.provides)}
    # Paths a step adds lazily are declared on accept, so declare them for the order check.
    declared = replace(
        study.initial_store,
        specs={**{p: ParameterSpec(p) for p in paths}, **study.initial_store.specs},
    )
    try:
        check_chain(steps, declared)
    except ChainError as exc:
        warnings.append(str(exc))
    for step in steps:
        missing = missing_requirements(step, study.prior_for(step.name))
        if missing:
            warnings.append(
                f"Step {step.name!r} requires {missing}, not in the store it starts from."
            )
    return warnings


class ParameterStoreWidget:
    """The study's parameter store after any step, with provenance, chain checks and file I/O.

    Loading a study replaces the shared `Study`'s contents in place and notifies its
    listeners, so every widget holding the same object follows.
    """

    def __init__(self, study: Study) -> None:
        self.study = study
        self._listeners: List[Callable[[], None]] = []

        self._step_picker = ChoiceField(label="Show store:")
        self._step_picker.observe(lambda _c: self._refresh_table(), names="selected_index")
        self._table = SelectableTable(
            label="Parameters",
            columns=["Parameter", "Path", "Species", "Value", "Set by", "Probe", "Source",
                     "Metric", "Note"],
            empty_text="The store is empty.",
        )
        self._warnings = W.HTML()
        self._path = W.Text(
            description="File:", value=self._default_path(),
            layout=W.Layout(width="100%"),
        )
        self._store_path = W.Text(
            description="Store file:", value="parameter_store.json",
            layout=W.Layout(width="100%"),
        )
        self._btn_save = W.Button(description="Save study", icon="save")
        self._btn_load = W.Button(description="Load study", icon="folder-open")
        self._btn_export = W.Button(description="Export current store (JSON)", icon="download")
        self._btn_save.on_click(lambda _b: self._file_action(self.save_study, self._path))
        self._btn_load.on_click(lambda _b: self._file_action(self.load_study, self._path))
        self._btn_export.on_click(
            lambda _b: self._file_action(self.export_store, self._store_path)
        )
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")

        toolbar = W.HBox([self._btn_save, self._btn_load], layout=W.Layout(flex_flow="row wrap"))
        toolbar.add_class("cadetgui-toolbar")
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(
                "<div class='cadetgui-panel-title'>"
                f"{term_html('parameter store', 'Parameter store')}</div>"
                f"<small>Every value carries its {term_html('provenance')}: the step that "
                f"set it, the {term_html('probe')} it was measured with, the runs and the "
                f"metric. \"After &lt;step&gt;\" shows that step's {term_html('posterior')}, "
                f"which is the {term_html('prior')} of the next step.</small>"
            ),
            self._step_picker,
            self._warnings,
            self._table,
            self._path,
            toolbar,
            self._store_path,
            self._btn_export,
            self.status,
        ])
        self.root.add_class("cadetgui-panel")

        self.refresh()
        study.add_listener(self.refresh)

    def _default_path(self) -> str:
        base = self.study.base_dir
        return str(base / "study.json") if base is not None else "study.json"

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Call `fn()` after the shown store changes."""
        self._listeners.append(fn)

    def refresh(self) -> None:
        """Re-read the study: step choices, chain warnings and the table."""
        options = [("Current (after the last accepted step)", CURRENT), ("Initial", INITIAL)]
        options += [
            (f"After {s.name}" + ("" if s.name in self.study.posteriors else " (not accepted)"),
             s.name)
            for s in self.study.steps
        ]
        self._step_picker.set_options(options)
        warnings = chain_warnings(self.study)
        self._warnings.value = "<br>".join(status_html("warn", w) for w in warnings)
        self._refresh_table()

    def show_after(self, step_name: Optional[str]) -> None:
        """Show the store after `step_name`; `None` is the current store, "" the initial one."""
        self._step_picker.value = CURRENT if step_name is None else (step_name or INITIAL)

    def get_value(self) -> ParameterStore:
        """Return the store being shown."""
        choice = self._step_picker.value
        if choice in (None, CURRENT):
            return self.study.current_store
        if choice == INITIAL:
            return self.study.initial_store
        store = self.study.initial_store
        for step in self.study.steps:
            store = self.study.posteriors.get(step.name, store)
            if step.name == choice:
                break
        return store

    def _refresh_table(self) -> None:
        store = self.get_value()
        rows, options = [], []
        for path, entry in sorted(store.entries.items()):
            spec = store.specs.get(path)
            values = (
                sorted(entry.value.items())
                if spec is not None and spec.species_indexed else [("", entry.value)]
            )
            prov = entry.provenance
            for species, value in values:
                rows.append([
                    parameter_label(path), path, species, _fmt(value),
                    (set_by_label(prov.step), "info"), prov.probe or "", prov.source or "",
                    _metric(prov.metric), prov.note or "",
                ])
                options.append((f"{path} {species}".strip(), (path, species)))
        self._table.set_options(options, rows=rows, select_none=True)
        for fn in list(self._listeners):
            fn()

    def _file_action(self, action: Callable[[str], Path], field: W.Text) -> None:
        try:
            path = action(field.value)
        except (OSError, ValueError, KeyError) as exc:
            self.status.value = status_html("error", f"{type(exc).__name__}: {exc}")
            return
        self.status.value = status_html("ok", f"{action.__name__.replace('_', ' ')}: {path}")

    def save_study(self, path: "Path | str") -> Path:
        """Write the study as JSON; data files stay referenced relative to `path`."""
        return self.study.save(path)

    def load_study(self, path: "Path | str") -> Path:
        """Replace the study's contents with the file's, in place, and notify its listeners."""
        loaded = Study.load(path)
        for f in dataclasses.fields(Study):
            if f.name != "_listeners":
                setattr(self.study, f.name, getattr(loaded, f.name))
        self.study.notify()
        return Path(path)

    def export_store(self, path: "Path | str") -> Path:
        """Write the current store (after the last accepted step) as JSON."""
        return self.study.current_store.save(path)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
