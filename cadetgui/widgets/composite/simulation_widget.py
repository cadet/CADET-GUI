from __future__ import annotations

import html
from typing import Any, Callable, List, Mapping, Optional, Tuple

import ipywidgets as W
from CADETProcess.processModel import Inlet, Outlet
from CADETProcess.solution import SolutionIO

from ...simulation import run_process
from .._chrome import style_tag
from .._series import reference_series, solution_series
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart
from ._code_view import CodeView

__all__ = ["SimulationWidget"]


def _solution_options(process: Any, results: Any) -> List[Tuple[str, Tuple[str, str]]]:
    """Inlets by their outlet and outlets by their inlet, named after the unit; others by port."""
    options = []
    for unit, ports in results.solution.items():
        model = getattr(process.flow_sheet, unit, None)
        for port, solution in ports.items():
            if not isinstance(solution, SolutionIO):
                continue
            if isinstance(model, Inlet):
                if port == "outlet":
                    options.append((unit, (unit, port)))
            elif isinstance(model, Outlet):
                if port == "inlet":
                    options.append((unit, (unit, port)))
            else:
                options.append((f"{unit}.{port}", (unit, port)))
    return options


class SimulationWidget:
    """Simulate a CADET-Process Process and plot the concentration at a chosen unit.

    Inlets and outlets are listed by their unit name (what an inlet delivers, what reaches
    an outlet), other units by port, e.g. `column.outlet`; it starts on the first outlet.
    A `reference` (CADET-Process `ReferenceIO`, e.g. measured data) is drawn dashed;
    `markers` (name: time in seconds, e.g. an expected breakthrough time) as vertical lines.
    """

    def __init__(
        self,
        process: Any,
        reference: Optional[Any] = None,
        markers: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.process = process
        self.reference = reference
        self.markers = dict(markers or {})
        self.results: Optional[Any] = None
        self._listeners: List[Callable[[Any], None]] = []
        self._btn_run = W.Button(description="Run simulation", icon="play", button_style="success")
        self._signal = ChoiceField(label="Show:", options=[])
        self.chart = ChromatogramChart(
            markers=[{"name": name, "time": time / 60} for name, time in self.markers.items()]
        )
        self.status = W.HTML()
        self.code_view = CodeView(self.code)
        title = html.escape(process.name)
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML(f"<div class='cadetgui-panel-title'>Simulation of {title}</div>"),
            self._btn_run,
            self._signal,
            self.chart,
            self.status,
            self.code_view.root,
        ])
        self.root.add_class("cadetgui-panel")
        self._btn_run.on_click(lambda _btn: self.run())
        self._signal.observe(lambda _change: self._plot(), names="selected_index")
        self._signal.observe(lambda _change: self.code_view.refresh(), names="selected_index")
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
        options = _solution_options(self.process, results)
        self._signal.set_options(options, keep_value=True)
        outlets = [
            value for _, value in options
            if isinstance(getattr(self.process.flow_sheet, value[0], None), Outlet)
        ]
        if first_run and outlets:
            self._signal.value = outlets[0]
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

    def code(self) -> str:
        """Return the CADET-Process code that simulates the process and plots the shown solution."""
        outlets = [u.name for u in self.process.flow_sheet.units if isinstance(u, Outlet)]
        unit, port = self._signal.value or (outlets[0] if outlets else "outlet", "inlet")
        lines = [
            "from CADETProcess.simulator import Cadet",
            "",
            "simulator = Cadet()",
            "simulation_results = simulator.simulate(process)",
        ]
        if not self.markers:
            return "\n".join(lines + [f"_ = simulation_results.solution.{unit}.{port}.plot()"])
        lines.append(f"fig, ax = simulation_results.solution.{unit}.{port}.plot()")
        lines += [
            f'_ = ax.axvline({time / 60:g}, color="gray", linestyle="--", label="{name}")'
            for name, time in self.markers.items()
        ]
        return "\n".join(lines)

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
