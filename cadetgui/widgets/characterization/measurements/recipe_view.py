"""A measurement's recipe summary, flow-path diagram and problems."""

from __future__ import annotations

from typing import Sequence

import ipywidgets as W

from ....characterization.comparison import Comparison
from ...diagrams.instrument import recipe_diagram_svg
from .labels import observed_unit, problems_html, recipe_summary_html

__all__ = ["RecipeView"]


class RecipeView:
    """Three HTML parts the host lays out: `summary`, `diagram` and `problems`."""

    def __init__(self) -> None:
        self.summary = W.HTML()
        self.diagram = W.HTML()
        self.problems = W.HTML()

    def show(self, comparison: Comparison, problems: Sequence[str]) -> None:
        """Show `comparison`'s recipe and `problems`."""
        self.summary.value = recipe_summary_html(comparison)
        self.diagram.value = recipe_diagram_svg(
            comparison.recipe, observe=observed_unit(comparison.solution_path), compact=True
        )
        self.problems.value = problems_html(problems)

    def clear(self, problem_html: str) -> None:
        """Show no recipe, only `problem_html`."""
        self.summary.value = self.diagram.value = ""
        self.problems.value = problem_html
