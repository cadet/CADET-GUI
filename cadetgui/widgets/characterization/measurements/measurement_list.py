"""The study's measurements, grouped by the chain step each one feeds."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import CHAIN_BY_ID, DEFAULT_CHAIN, EXPERIMENT_TYPES
from ....characterization.study import Study
from ...elements import SelectableTable
from ...ui.layout import section_title
from .add_flow import AddMeasurementFlow
from .labels import channel_label, step_of

__all__ = ["MeasurementList"]


class MeasurementList:
    """One table per chain step, an add button per step, and the open stepper in place.

    `on_select(name)` is called when the user picks a measurement, `on_add(step_id)`
    when they ask to add one for a step.
    """

    def __init__(
        self,
        study: Study,
        flow: AddMeasurementFlow,
        *,
        on_select: Callable[[str], None],
        on_add: Callable[[str], None],
    ) -> None:
        self.study = study
        self._flow = flow
        self._on_select = on_select
        self._on_add = on_add
        self._loading = False
        self.tables: Dict[Optional[str], SelectableTable] = {}
        self._buttons: Dict[str, W.Button] = {}
        self.box = W.VBox([])

    def table_for(self, key: Optional[str]) -> SelectableTable:
        """Return the table of step `key` (None: not assigned to a step)."""
        if key not in self.tables:
            table = SelectableTable(
                columns=["Name", "Experiment type", "Detector", "Used in", "Status"],
                empty_text="No measurements yet.",
            )
            table.observe(lambda _c, key=key: self._on_table(key), names="selected_index")
            self.tables[key] = table
        return self.tables[key]

    def group_button(self, step_id: str) -> W.Button:
        """Return the "Add measurement for this step" button of `step_id`."""
        if step_id not in self._buttons:
            button = W.Button(description="Add measurement for this step", icon="plus",
                              layout=W.Layout(width="auto"))
            button.on_click(lambda _b: self._on_add(step_id))
            self._buttons[step_id] = button
        return self._buttons[step_id]

    def refresh(self, selected: Optional[str]) -> None:
        """Rebuild the groups from the study and select `selected`."""
        groups: Dict[Optional[str], List[Comparison]] = {}
        for c in self.study.comparisons:
            groups.setdefault(step_of(c), []).append(c)
        children: List[W.Widget] = []
        order = [g.id for g in DEFAULT_CHAIN] + ([None] if None in groups else [])
        flow = self._flow
        target = flow.target_step if flow.is_open else None
        placed = target in order

        def flow_here(key: Optional[str]) -> bool:
            return flow.is_open and placed and key == target

        if flow.is_open and not placed:
            children.append(flow.root)
        was_loading = self._loading
        self._loading = True
        try:
            for key in order:
                members = groups.get(key, [])
                guide = CHAIN_BY_ID.get(key) if key is not None else None
                if guide is not None:
                    labels = ", ".join(EXPERIMENT_TYPES[t].label for t in guide.experiment_types)
                    heading = section_title(f"{html.escape(guide.title)} "
                                            f"<span class='cadetgui-note'>· {len(members)} "
                                            f"measurement(s) · expects: {html.escape(labels)}"
                                            "</span>")
                else:
                    heading = section_title(
                        "Not assigned to a step <span class='cadetgui-note'>· set an "
                        "experiment type under Advanced to assign one</span>"
                    )
                children.append(heading)
                if flow_here(key):
                    children.append(flow.root)
                if members:
                    table = self.table_for(key)
                    table.set_options(
                        [(c.name, c.name) for c in members],
                        rows=[self._row_cells(c) for c in members],
                        select_none=True,
                    )
                    children.append(table)
                if guide is not None and not flow_here(key):
                    children.append(self.group_button(key))
            for key in [k for k in self.tables if not groups.get(k)]:
                del self.tables[key]
        finally:
            self._loading = was_loading
        self.box.children = children
        self.select(selected)

    def select(self, name: Optional[str]) -> None:
        """Select the row of `name` in every table (clearing the others)."""
        was_loading = self._loading
        self._loading = True
        try:
            for table in self.tables.values():
                table.value = name
        finally:
            self._loading = was_loading

    def _row_cells(self, c: Comparison) -> List[Any]:
        n = len(self.study.measurement_problems(c))
        chip = ("ok", "ok") if n == 0 else (f"{n} problem{'s' * (n > 1)}", "error")
        experiment_type = EXPERIMENT_TYPES.get(c.experiment_type or "")
        return [
            c.name,
            experiment_type.label if experiment_type else "not set",
            channel_label(c.channel),
            ", ".join(self.study.steps_using(c.name)) or "–",
            chip,
        ]

    def _on_table(self, key: Optional[str]) -> None:
        table = self.tables.get(key)
        if self._loading or table is None or table.value is None:
            return
        self._on_select(table.value)
