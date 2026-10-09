from __future__ import annotations

import html
from typing import Any, Callable, List, Optional

import ipywidgets as W

from ...cadetprocessadapter import classify_signal_ports, measurable_signal_options
from ...simulation import run_process
from .._chrome import style_tag
from .._series import solution_series
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart

__all__ = ["SimulationWidget"]


class SimulationWidget:
    """Simulate a CADET-Process Process and plot the concentration at a chosen unit."""

    def __init__(self, process: Any) -> None:
        self.process = process
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
        ports = classify_signal_ports(results)
        self._signal.set_options(measurable_signal_options(self.process, ports), keep_value=True)
        self._plot()
        self.status.value = status_html(
            "ok", f"Simulation finished in {results.time_elapsed:.2f} s."
        )
        for fn in list(self._listeners):
            fn(results)
        return results

    def _plot(self) -> None:
        if self.results is None or self._signal.value is None:
            return
        unit, port = self._signal.value
        self.chart.series = solution_series(self.results.solution[unit][port]) or []

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
