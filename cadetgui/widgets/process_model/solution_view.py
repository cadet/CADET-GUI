"""Pick a position in a simulated process and see its concentrations."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W

from ..elements import ChoiceField, ChromatogramChart
from ..ui.plotting import reference_series, solution_series

__all__ = ["SolutionView"]

Option = Tuple[str, Tuple[str, str]]


class SolutionView:
    """A signal picker and chart for one simulation result.

    `show(results, options)` offers `(label, (unit, port))` options and draws the picked
    one per component; a solution that is not a time × component trace is drawn with its
    own matplotlib plot instead. A `reference` (CADET-Process `ReferenceIO`) is drawn
    dashed, `markers` (name: time in seconds) as vertical lines.
    """

    def __init__(
        self,
        *,
        label: str = "Signal:",
        y_label: str = "",
        reference: Optional[Any] = None,
        markers: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.results: Optional[Any] = None
        self.reference = reference
        self.picker = ChoiceField(label=label, options=[])
        self.chart = ChromatogramChart(
            y_label=y_label,
            markers=[{"name": name, "time": time / 60} for name, time in (markers or {}).items()],
        )
        self.fallback_plot = W.Output(layout=W.Layout(display="none"))
        self.root = W.VBox([self.picker, self.chart, self.fallback_plot])
        self.picker.observe(lambda _change: self.redraw(), names="selected_index")

    @property
    def selected(self) -> Optional[Tuple[str, str]]:
        """The picked `(unit, port)`, or None."""
        return self.picker.value

    def show(
        self,
        results: Any,
        options: Sequence[Option],
        default: Optional[Tuple[str, str]] = None,
    ) -> None:
        """Offer `options` of `results`, keep the picked one if still offered, else `default`."""
        self.results = results
        first = self.picker.value is None
        self.picker.set_options(list(options), keep_value=True)
        if first and default is not None:
            self.picker.value = default
        self.redraw()

    def clear(self) -> None:
        """Forget the results and empty the picker and chart."""
        self.results = None
        self.picker.set_options([])
        self.fallback_plot.clear_output()
        self.fallback_plot.layout.display = "none"
        self.redraw()

    def redraw(self) -> None:
        """Draw the picked solution and the reference."""
        series: List[dict] = []
        solution = None
        if self.results is not None and self.picker.value is not None:
            unit, port = self.picker.value
            solution = self.results.solution[unit][port]
            series = solution_series(solution)
        if solution is not None and series is None:
            self._show_fallback(solution)
            return
        self.fallback_plot.layout.display = "none"
        if solution is not None:
            self.chart.layout.display = ""
        if self.reference is not None:
            ref = self.reference
            series = [*series, reference_series(ref.name, ref.time, ref.solution[:, 0])]
        self.chart.series = series

    def _show_fallback(self, solution: Any) -> None:
        self.chart.series = []
        self.chart.layout.display = "none"
        self.fallback_plot.layout.display = ""
        self.fallback_plot.clear_output(wait=True)
        with self.fallback_plot:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, _ax = solution.plot()
            display(fig)
            plt.close(fig)
