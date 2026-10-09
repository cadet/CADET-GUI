from __future__ import annotations

import math
from html import escape
from typing import Any, Callable, List, Optional, Sequence

import ipywidgets as W
import numpy as np

from ...parameters import describe_parameter
from .._units import unit_html
from ..elements import PolynomialChart, TextField
from ._parameter_values import _number_text

__all__ = ["PolynomialEditor", "profile_svg"]

_SAMPLES_PER_SECTION = 60
_CURVE = "#4a7fb5"
_AXIS = "#5b6370"


def _coefficient_unit(base: str, power: int) -> str:
    if not base or power == 0:
        return base
    time = r"\mathrm{s}" if power == 1 else rf"\mathrm{{s}}^{{{power}}}"
    return rf"\frac{{{base}}}{{{time}}}"


def profile_svg(times: Sequence[float], values: Sequence[float], symbol: str, unit: str) -> str:
    """Draw a profile over time as a static picture, labelled at zero, its maximum and end."""
    width, height = 420, 170
    left, right, top, bottom = 70, 30, 24, 34
    end = times[-1] if times[-1] > 0 else 1.0
    top_value = max(max(values), 0.0)
    low_value = min(min(values), 0.0)
    span = (top_value - low_value) or 1.0

    def x(t: float) -> float:
        return left + t / end * (width - left - right)

    def y(v: float) -> float:
        return height - bottom - (v - low_value) / (span * 1.15) * (height - top - bottom)

    points = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in zip(times, values))
    axis = f'stroke="{_AXIS}" stroke-width="1.5"'
    label = f'fill="{_AXIS}" font-size="13"'
    peak = (
        f'<text x="{left - 8}" y="{y(top_value) + 4:.1f}" text-anchor="end" font-size="13">'
        f"{escape(_number_text(top_value))}</text>"
        f'<line x1="{left - 4}" y1="{y(top_value):.1f}" x2="{left}" '
        f'y2="{y(top_value):.1f}" {axis}/>'
        if top_value > 0 else ""
    )
    return (
        f'<div style="max-width:{width}px"><svg viewBox="0 0 {width} {height}" '
        'style="width:100%;height:auto;display:block" '
        'font-family="var(--cg-font, system-ui, sans-serif)">'
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right + 12}" '
        f'y2="{height - bottom}" {axis}/>'
        f'<line x1="{left}" y1="{height - bottom}" x2="{left}" y2="{top - 10}" {axis}/>'
        f'<polyline points="{points}" fill="none" stroke="{_CURVE}" stroke-width="3"/>'
        f"{peak}"
        f'<text x="{left - 8}" y="{y(0) + 4:.1f}" text-anchor="end" font-size="13">0</text>'
        f'<text x="{left}" y="{height - 12}" text-anchor="middle" {label}>0</text>'
        f'<text x="{x(end):.1f}" y="{height - 12}" text-anchor="middle" {label}>'
        f"{escape(_number_text(end))} s</text>"
        f'<text x="{width - right + 16}" y="{height - bottom + 4}" font-style="italic" '
        f"{label}>t</text>"
        f'<text x="{left - 8}" y="{top - 12}" text-anchor="end" font-style="italic" '
        f'font-size="13">{escape(symbol)}</text>'
        f"</svg></div><small style='color:{_AXIS}'>{unit_html(unit)}</small>"
    )


class PolynomialEditor:
    """Edit one cubic inlet profile, e.g. `Inlet.c` of one component, by its coefficients.

    A picture shows the resulting profile: over the cycle of `process` (CADET restarts the
    polynomial at every section), or over `duration` seconds without a process. With
    `draggable`, a chart with four handles over the first section replaces the picture.
    """

    def __init__(
        self,
        owner: Any,
        name: str,
        index: Optional[int] = None,
        *,
        process: Any = None,
        duration: float = 600.0,
        on_change: Optional[Callable[[], None]] = None,
        draggable: bool = False,
    ) -> None:
        self.owner = owner
        self.name = name
        self.index = index
        self.process = process
        self.duration = duration
        self.draggable = draggable
        self._on_change = on_change
        self._refreshing = False
        self._unit, _description = describe_parameter(owner, name)
        self.chart = PolynomialChart(y_label=name) if draggable else W.HTML()
        self.fields: List[TextField] = [
            TextField(label=f"a{k}", units=_coefficient_unit(self._unit, k)) for k in range(4)
        ]
        self._note = W.HTML()
        component = None if index is None else owner.component_system.names[index]
        title = name if component is None else f"{name} · {component}"
        self._symbol = name if component is None else f"{name} ({component})"
        self.root = W.VBox([
            W.HTML(f"<code class='cadetgui-param-label'>{escape(title)}</code>"),
            *self.fields,
            self._note,
            self.chart,
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
        if self.process is None:
            return [(0.0, self.duration)]
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
        cycle_time = self.duration if self.process is None else float(self.process.cycle_time)
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
            self.chart.value = profile_svg(times, values, self._symbol, self._unit)
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
