from __future__ import annotations

import html
from typing import Any, Callable, List, Optional, Tuple

import ipywidgets as W
from CADETProcess.solution import SolutionIO

from ...simulation import run_process
from .._chrome import style_tag
from .._series import reference_series, solution_series
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart

__all__ = ["SimulationWidget"]


def _solution_options(results: Any) -> List[Tuple[str, Tuple[str, str]]]:
    return [
        (f"{unit}.{port}", (unit, port))
        for unit, ports in results.solution.items()
        for port, solution in ports.items()
        if isinstance(solution, SolutionIO)
    ]


class SimulationWidget:
    """Simulate a CADET-Process Process and plot the concentration at a chosen unit.

    Every unit's `inlet` and `outlet` solution can be shown, labelled by its path in
    `results.solution`, e.g. `column.outlet`. A `reference` (CADET-Process `ReferenceIO`,
    e.g. measured data) is drawn dashed.
    """

    def __init__(self, process: Any, reference: Optional[Any] = None) -> None:
        self.process = process
        self.reference = reference
        self.results: Optional[Any] = None
        self._listeners: List[Callable[[Any], None]] = []
        self._btn_run = W.Button(description="Run simulation", icon="play", button_style="success")
        self._signal = ChoiceField(label="Show:", options=[])
        self.chart = ChromatogramChart()
        self.status = W.HTML()
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Simulation of {title}</div>"),
            self._btn_run,
            self._signal,
            self.chart,
            self.status,
        ])
        self.root.add_class("cadetgui-panel")
        self._btn_run.on_click(lambda _btn: self.run())
        self._signal.observe(lambda _change: self._plot(), names="selected_index")
        self._plot()

    def run(self) -> Optional[Any]:
        """Simulate the process with CADET and show the results."""
        self._btn_run.disabled = True
        self.status.value = status_html("running", "Running simulation…")
        try:
            results = run_process(self.process)
        except Exception as exc:  # noqa: BLE001
            self.status.value = status_html("error", f"Simulation failed: {exc}")
            return None
        finally:
            self._btn_run.disabled = False
        self.results = results
        first_run = self._signal.value is None
        options = _solution_options(results)
        self._signal.set_options(options, keep_value=True)
        if first_run and ("outlet", "outlet") in [value for _, value in options]:
            self._signal.value = ("outlet", "outlet")
        self._plot()
        self.status.value = status_html(
            "ok", f"Simulation finished in {results.time_elapsed:.2f} s."
        )
        for fn in list(self._listeners):
            fn(results)
        return results

    def _plot(self) -> None:
        series = []
        if self.results is not None and self._signal.value is not None:
            unit, port = self._signal.value
            series = solution_series(self.results.solution[unit][port]) or []
        if self.reference is not None:
            ref = self.reference
            series.append(reference_series(ref.name, ref.time, ref.solution[:, 0]))
        self.chart.series = series

    def get_value(self) -> Optional[Any]:
        """Return the SimulationResults of the last run, or None."""
        return self.results

    def add_listener(self, fn: Callable[[Any], None]) -> None:
        """Call `fn(results)` after every successful run."""
        self._listeners.append(fn)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
