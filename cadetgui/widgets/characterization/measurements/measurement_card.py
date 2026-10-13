"""The card of the selected measurement: recipe, diagram, problems and measured trace."""

from __future__ import annotations

import html
from typing import List, Optional

import ipywidgets as W
import numpy as np

from ....characterization.comparison import Comparison
from ....instrument.process_builder import check_recipe
from ....io.experimental_data import to_time
from ...elements import ChromatogramChart
from ...ui.html import status_html
from ...ui.layout import note, section, section_title
from .labels import reference_series
from .recipe_view import RecipeView

__all__ = ["MeasurementCard"]

_MEASURED_HINT = (
    "The measured trace as the fit compares it: shifted onto the simulated injection, "
    "baseline-corrected and scaled. Check alignment and baseline here; the step pages "
    "compare it with simulations."
)


class MeasurementCard:
    """Show one comparison; `advanced` (its editor) is placed at the bottom."""

    def __init__(self, advanced: W.Widget) -> None:
        self.title = W.HTML()
        self.recipe = RecipeView()
        self.recipe.problems.add_class("cadetgui-status")
        self.measured_chart = ChromatogramChart(
            view_width=480, view_height=240, y_label="Signal", x_label="Time / min"
        )
        self.measured_note = note()
        self.root = section([
            self.title,
            self.recipe.summary,
            self.recipe.diagram,
            section_title("Problems"),
            self.recipe.problems,
            section_title("Measured trace"),
            note(_MEASURED_HINT),
            self.measured_chart,
            self.measured_note,
            advanced,
        ])

    def show(self, comparison: Comparison, problems: List[str]) -> None:
        """Show `comparison` with `problems`, or why its trace cannot be prepared."""
        self.title.value = (
            f"<div class='cadetgui-panel-title'>{html.escape(comparison.name)}</div>"
        )
        unprepared = self._show_measured(comparison)
        if unprepared and not problems:
            problems = [unprepared]
        self.recipe.show(comparison, problems)

    def _show_measured(self, comparison: Comparison) -> Optional[str]:
        """Plot the measured trace as the fit compares it, else the raw trace; return why."""
        run = comparison.run
        if run is None or comparison.channel not in run.channels:
            self.measured_chart.series = []
            self.measured_note.value = "No measured data loaded."
            return None
        try:
            check = check_recipe(comparison.recipe, comparison.overrides)
            if check.error is not None:
                raise ValueError(check.error)
            reference = comparison.build_reference(check.process)
            time = np.asarray(reference.time)
            values = np.asarray(reference.solution)[:, 0]
            problem = None
        except Exception as exc:  # noqa: BLE001 -- shown with the raw trace instead
            time, values = to_time(run, comparison.channel, comparison.resolved_flow_rate)
            problem = str(exc)
        self.measured_chart.series = [reference_series(comparison.name, time / 60.0, values)]
        self.measured_note.value = (
            status_html("warn", "Showing the raw trace; it cannot be prepared for the fit.")
            if problem else ""
        )
        return problem
