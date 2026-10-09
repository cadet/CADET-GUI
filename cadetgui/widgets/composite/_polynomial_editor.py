from __future__ import annotations

import math
from html import escape
from typing import Any, Callable, List, Optional

import ipywidgets as W
import numpy as np

from ...parameters import describe_parameter
from ..elements import LineChart, PolynomialChart, TextField
from ._parameter_values import _number_text

__all__ = ["PolynomialEditor"]

_SAMPLES_PER_SECTION = 60


def _coefficient_unit(base: str, power: int) -> str:
    if not base or power == 0:
        return base
    time = r"\mathrm{s}" if power == 1 else rf"\mathrm{{s}}^{{{power}}}"
    return rf"\frac{{{base}}}{{{time}}}"


class PolynomialEditor:
    """Edit one cubic inlet profile, e.g. `Inlet.c` of one component, by its coefficients.

    The chart shows the profile over the whole cycle, since CADET restarts the polynomial
    at every section of the process. With `draggable`, four handles over the first section
    shape it as well.
    """

    def __init__(
        self,
        process: Any,
        owner: Any,
        name: str,
        index: Optional[int] = None,
        on_change: Optional[Callable[[], None]] = None,
        draggable: bool = False,
    ) -> None:
        self.process = process
        self.draggable = draggable
        self.owner = owner
        self.name = name
        self.index = index
        self._on_change = on_change
        self._refreshing = False
        unit, _description = describe_parameter(owner, name)
        self.chart = PolynomialChart(y_label=name) if draggable else LineChart(y_label=name)
        self.fields: List[TextField] = [
            TextField(label=f"a{k}", units=_coefficient_unit(unit, k)) for k in range(4)
        ]
        self._note = W.HTML()
        title = name if index is None else f"{name} · {owner.component_system.names[index]}"
        self.root = W.VBox([
            W.HTML(f"<div class='cadetgui-param-label'>{escape(title)}</div>"),
            self._note,
            self.chart,
            *self.fields,
        ])
        if draggable:
            self.chart.observe(lambda _change: self._on_drag(), names="points")
        for k, field in enumerate(self.fields):
            field.observe(lambda change, k=k: self._on_field(k, change), names="value")
        self.refresh()

    def coefficients(self) -> np.ndarray:
        """Return the four coefficients `[a0, a1, a2, a3]` of the profile."""
        values = np.asarray(getattr(self.owner, self.name), dtype=float)
        return values[self.index] if self.index is not None else values

    def _set_coefficients(self, coefficients: np.ndarray) -> None:
        if self.index is None:
            setattr(self.owner, self.name, list(coefficients))
        else:
            values = np.asarray(getattr(self.owner, self.name), dtype=float)
            values[self.index] = coefficients
            setattr(self.owner, self.name, values.tolist())
        self.refresh()
        if self._on_change is not None:
            self._on_change()

    def _sections(self) -> List[tuple[float, float]]:
        bounds = list(self.process.section_times)
        return list(zip(bounds[:-1], bounds[1:]))

    def refresh(self) -> None:
        """Show the current coefficients, e.g. after the cycle time or events changed."""
        self._refreshing = True
        try:
            self._show()
        finally:
            self._refreshing = False

    def _show(self) -> None:
        coefficients = self.coefficients()
        for field, value in zip(self.fields, coefficients):
            field.value = _number_text(float(value) + 0.0)
            field.error = ""
        cycle_time = float(self.process.cycle_time)
        if not math.isfinite(cycle_time) or cycle_time <= 0:
            self.chart.layout.display = "none"
            self._note.value = "<small>Set a cycle time to see the profile.</small>"
            return
        self.chart.layout.display = ""
        self._note.value = ""
        polynomial = np.polynomial.Polynomial(coefficients)
        times: List[float] = []
        values: List[float] = []
        for start, end in self._sections():
            t = np.linspace(start, end, _SAMPLES_PER_SECTION)
            times += t.tolist()
            values += polynomial(t - start).tolist()
        if not self.draggable:
            self.chart.series = [
                {"name": self.name, "times": [t / 60 for t in times], "values": values}
            ]
            return
        duration = self._sections()[0][1]
        self.chart.duration = duration
        self.chart.cycle_time = cycle_time
        self.chart.curve = {"times": times, "values": values}
        self.chart.points = polynomial(np.linspace(0, duration, 4)).tolist()

    def _on_drag(self) -> None:
        if self._refreshing:
            return
        times = np.linspace(0, self.chart.duration, 4)
        coefficients = np.linalg.solve(np.vander(times, 4, increasing=True), self.chart.points)
        self._set_coefficients(coefficients)

    def _on_field(self, k: int, change: dict) -> None:
        if self._refreshing:
            return
        try:
            value = float(change["new"])
        except ValueError:
            self.fields[k].error = "Enter a number."
            return
        coefficients = self.coefficients().copy()
        coefficients[k] = value
        self._set_coefficients(coefficients)
