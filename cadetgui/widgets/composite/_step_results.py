"""Pareto candidates of a finished characterization step run: table, previews, export."""

from __future__ import annotations

import copy
import csv
import html
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W
import numpy as np

from ... import characterization_runner
from ...characterization_runner import Candidate, StepResult, StepSetup
from ...parameter_store import ParameterStore
from .._help import term_html
from .._series import decimate_minmax, reference_series
from .._status import status_html
from ..elements import ChromatogramChart, SelectableTable


def _preview_series(preview: Any) -> list:
    times, values = decimate_minmax(
        np.asarray(preview.simulated_time, dtype=float) / 60.0,
        np.asarray(preview.simulated_values, dtype=float),
    )
    return [
        {"name": "Simulated", "times": times, "values": values},
        reference_series("Measured", preview.reference_time, preview.reference_values),
    ]


def _preview_title(preview: Any) -> str:
    return f"<b>{html.escape(preview.name)}: {term_html(preview.metric)} = {preview.value:.4g}</b>"


class _CandidateResults:
    """Front candidates of one run, per-comparison previews, Accept and CSV export."""

    def __init__(self, on_accept: Callable[[Candidate], None]) -> None:
        self._on_accept = on_accept
        self.result: Optional[StepResult] = None
        self._setup: Optional[StepSetup] = None
        self._prior: Optional[ParameterStore] = None
        self.candidates: List[Candidate] = []
        self._previews: Dict[int, list] = {}

        self.table = SelectableTable(label="Candidates", empty_text="No candidates.")
        self.table.observe(self._on_pick, names="selected_index")
        self._charts = W.HBox(layout=W.Layout(flex_flow="row wrap"))
        self.btn_accept = W.Button(
            description="Accept candidate", icon="check", button_style="success"
        )
        self.btn_accept.on_click(lambda _b: self._accept_clicked())
        self.export_path = W.Text(description="CSV file:", value="candidates.csv")
        self._btn_export = W.Button(description="Export candidates (CSV)", icon="download")
        self._btn_export.on_click(lambda _b: self._export_clicked())
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")

        self.root = W.VBox([
            W.HTML(
                "<div class='cadetgui-section-title'>"
                f"{term_html('Pareto candidate', 'Pareto candidates')}</div>"
                f"<small>Pick one: {term_html('best average')} has the lowest mean error "
                f"over all measurements; \"best &lt;measurement&gt;\" matches that run best. "
                f"Errors are shown as {term_html('NRMSE')} unless the measurement sets "
                "another metric.</small>"
            ),
            self.table,
            W.HBox([self.btn_accept, self.export_path, self._btn_export],
                   layout=W.Layout(flex_flow="row wrap")),
            self.status,
            self._charts,
        ], layout=W.Layout(display="none"))

    def show(self, result: StepResult, setup: StepSetup, prior: ParameterStore) -> None:
        """List `result`'s candidates and preview the best-average one."""
        self.result, self._setup, self._prior = result, setup, prior
        self.candidates = characterization_runner.pareto_candidates(result)
        self._previews = {}
        self.table.columns = [
            "Tags", *result.variable_names,
            *(f"{c.name} ({c.metric})" for c in setup.comparisons),
        ]
        self.table.set_options(
            [(", ".join(c.tags), i) for i, c in enumerate(self.candidates)],
            rows=[
                [(", ".join(c.tags), "info"), *(f"{v:.4g}" for v in (*c.x, *c.f))]
                for c in self.candidates
            ],
            keep_value=False, select_none=True,
        )
        self.btn_accept.layout.display = "" if self.candidates else "none"
        self.btn_accept.disabled = False
        self.root.layout.display = ""
        self.status.value = "" if self.candidates else status_html(
            "warn", "The run produced no front to choose from."
        )
        if self.candidates:
            self.table.value = 0

    def clear(self) -> None:
        self.result, self.candidates, self._previews = None, [], {}
        self.table.set_options([], rows=[])
        self._charts.children = []
        self.status.value = ""
        self.root.layout.display = "none"

    @property
    def selected(self) -> Optional[Candidate]:
        index = self.table.value
        return self.candidates[index] if index is not None else None

    def preview_store(self, candidate: Candidate) -> ParameterStore:
        """Return the store `candidate` would be accepted as, computed on copied processes."""
        built = copy.deepcopy(self.result.built)
        return characterization_runner.posterior(self._setup, built, self._prior, candidate)

    def _on_pick(self, _change: Any) -> None:
        candidate = self.selected
        if candidate is None:
            self._charts.children = []
            return
        index = self.candidates.index(candidate)
        self.status.value = status_html("running", "Simulating the candidate…")
        try:
            if index not in self._previews:
                store = self.preview_store(candidate)
                self._previews[index] = [c.evaluate(store) for c in self._setup.comparisons]
        except Exception as exc:  # noqa: BLE001 -- shown to the user
            self.status.value = status_html("error", f"Preview failed: {exc}")
            return
        self.status.value = ""
        self._charts.children = [self._chart(p) for p in self._previews[index]]

    @staticmethod
    def _chart(preview: Any) -> W.VBox:
        chart = ChromatogramChart(
            series=_preview_series(preview), view_width=420, view_height=240, y_label="Signal",
        )
        return W.VBox([W.HTML(_preview_title(preview)), chart])

    def previews_of(self, candidate: Candidate) -> Optional[list]:
        """Return the simulated previews of `candidate` if it has been previewed."""
        if candidate not in self.candidates:
            return None
        return self._previews.get(self.candidates.index(candidate))

    def _accept_clicked(self) -> None:
        candidate = self.selected
        if candidate is None:
            self.status.value = status_html("warn", "Pick a candidate first.")
            return
        self._on_accept(candidate)

    def _export_clicked(self) -> None:
        try:
            path = self.export_csv(self.export_path.value)
        except (OSError, ValueError) as exc:
            self.status.value = status_html("error", str(exc))
            return
        self.status.value = status_html("ok", f"Wrote {path}.")

    def export_csv(self, path: "Path | str") -> Path:
        """Write the candidates (tags, variables, objectives) to `path`."""
        if self.result is None:
            raise ValueError("No candidates to export.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["tags", *self.result.variable_names, *self.result.objective_names])
            for c in self.candidates:
                writer.writerow(["; ".join(c.tags), *c.x, *c.f])
        return path
