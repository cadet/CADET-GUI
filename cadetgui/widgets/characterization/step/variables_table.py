"""The variables table of a step setup: fit or fixed, current value, bounds."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List

import ipywidgets as W

from ....characterization.guide import starting_values
from ....characterization.runner import fitted_variables
from ....characterization.stages import VariableDef, describe_stage
from ....characterization.study import Study
from ...ui.format import unit_html
from ...ui.html import status_html
from ..help import term_html

_VARIABLES_HELP = (
    "<div class='cadetgui-note'>"
    "<b>Fit</b> ticked: the optimizer searches this parameter between its lower and upper "
    "bound, starting from its current value, and the accepted candidate's value is written "
    "to the parameter store. Unticked, the parameter is <b>fixed</b>: it keeps its current "
    "value (from an earlier step, the starting values or the process setup) and this step "
    "does not change it. Keep a parameter fixed when your measurements cannot tell it "
    "apart from another one, e.g. characteristic charge and equilibrium constant from only "
    "a few similar gradients. "
    "<b>Dependent</b> variables are computed from the fitted ones and have no bounds."
    "</div>"
)

_FIT_TOOLTIP = (
    "Ticked: the optimizer fits this parameter between its bounds. Unticked: it is kept "
    "fixed at its current value."
)


class VariablesTable:
    """One row per step variable: Fit box, current value, parameter path, bounds."""

    def __init__(
        self,
        study: Study,
        on_bounds_edit: Callable[[Any], None],
        on_fit_toggle: Callable[[Any], None],
    ) -> None:
        self._study = study
        self._on_bounds_edit = on_bounds_edit
        self._on_fit_toggle = on_fit_toggle
        self.variables: List[VariableDef] = []
        self.bound_fields: Dict[str, tuple[W.FloatText, W.FloatText]] = {}
        self.fit_boxes: Dict[str, W.Checkbox] = {}
        self.current_cells: Dict[str, W.HTML] = {}
        self.box = W.VBox()

    def rebuild(self, stage: str, options: dict, bounds: dict, frozen: Any) -> None:
        """Rebuild the rows for step type `stage` with `options`, `bounds` and `frozen`."""
        self.bound_fields, self.fit_boxes, self.current_cells = {}, {}, {}
        try:
            self.variables = describe_stage(stage, **options)
        except ValueError as exc:
            self.variables = []
            self.box.children = [W.HTML(status_html("warn", str(exc)))]
            return

        header = [
            term_html("fixed variable", "Fit"),
            "Variable", "Current value", "Parameter path", "Lower bound", "Upper bound",
        ]
        cells: List[W.Widget] = [W.HTML(f"<b>{h}</b>") for h in header]
        for var in self.variables:
            path = html.escape(var.parameter_path or "(helper)")
            current = W.HTML("—")
            if var.parameter_path is not None:
                self.current_cells[var.name] = current
            if var.is_dependent:
                cells += [
                    W.HTML("<em>dependent</em>"), W.Label(var.name), current,
                    W.HTML(f"<code>{path}</code>"), W.Label("—"), W.Label("—"),
                ]
                continue
            lb, ub = bounds.get(var.name, (var.lb, var.ub))
            lb_field = W.FloatText(value=float(lb), layout=W.Layout(width="120px"))
            ub_field = W.FloatText(value=float(ub), layout=W.Layout(width="120px"))
            fit = W.Checkbox(
                value=var.name not in frozen, description="Fit", indent=False,
                tooltip=_FIT_TOOLTIP, layout=W.Layout(width="auto"),
            )
            for control in (lb_field, ub_field):
                control.observe(self._on_bounds_edit, names="value")
            fit.observe(self._on_fit_toggle, names="value")
            self.bound_fields[var.name] = (lb_field, ub_field)
            self.fit_boxes[var.name] = fit
            cells += [
                fit, W.Label(var.name), current, W.HTML(f"<code>{path}</code>"),
                lb_field, ub_field,
            ]
        self.box.children = [
            W.HTML(_VARIABLES_HELP),
            W.GridBox(cells, layout=W.Layout(
                grid_template_columns="70px 200px 200px 1fr 130px 130px", align_items="center",
            )),
        ]

    def refresh_current_values(self, setup: Any) -> None:
        """Fill the "Current value" column from `setup`'s prior or the process setup."""
        if not self.current_cells:
            return
        try:
            values = starting_values(self._study, setup, self.variables)
        except Exception:  # noqa: BLE001 -- unbuildable recipes are reported elsewhere
            values = {}
        for name, cell in self.current_cells.items():
            start = values.get(name)
            if start is None:
                text = "—"
            else:
                unit = unit_html(start.unit)
                text = (
                    f"{html.escape(start.text)}{' ' + unit if unit else ''}"
                    f"<br><small>{html.escape(start.source)}</small>"
                )
            if cell.value != text:
                cell.value = text

    def bounds(self) -> dict:
        """Return the bounds that differ from the step type's defaults."""
        defaults = {v.name: (v.lb, v.ub) for v in self.variables}
        bounds = {}
        for name, (lb, ub) in self.bound_fields.items():
            pair = (float(lb.value), float(ub.value))
            if pair != defaults.get(name):
                bounds[name] = pair
        return bounds

    def frozen(self) -> tuple:
        """Return the names of the variables kept fixed."""
        return tuple(n for n, box in self.fit_boxes.items() if not box.value)

    def n_fitted(self) -> int:
        """Return how many variables are fitted."""
        return len(fitted_variables(self.variables, self.frozen()))

    def set_locked(self, locked: bool) -> None:
        """Make the bounds and Fit boxes read-only (or editable again)."""
        for pair in self.bound_fields.values():
            for field in pair:
                field.disabled = locked
        for box in self.fit_boxes.values():
            box.disabled = locked
