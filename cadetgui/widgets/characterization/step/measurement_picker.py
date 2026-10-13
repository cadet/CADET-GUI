"""The measurement rows of a step setup: one tick box per measurement the step can fit."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ....characterization.comparison import Comparison
from ....characterization.guide import CHAIN_BY_ID, EXPERIMENT_TYPES, ChainStepGuide
from ....characterization.study import Study
from ...ui.html import status_html
from ..measurements.labels import measurement_caption


def _does_not_fit_html(comparison: Comparison) -> str:
    experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
    if experiment is None:
        reason = "it has no experiment type"
    else:
        feeds = CHAIN_BY_ID.get(experiment.step_id)
        reason = f"{experiment.label} feeds {feeds.title if feeds else experiment.step_id}"
    return status_html(
        "warn", f"Does not fit this step ({reason}). Untick to remove it from the step."
    )


class MeasurementPicker:
    """Tick boxes for the study's measurements; a chain step lists the ones that feed it."""

    def __init__(
        self,
        study: Study,
        on_toggle: Callable[[], None],
        on_add: Optional[Callable[[], None]] = None,
    ) -> None:
        self._study = study
        self._on_toggle = on_toggle
        self._on_add = on_add
        self.boxes: Dict[str, W.Checkbox] = {}
        self.excluded: Optional[set[str]] = None
        self.rows_guide: Optional[str] = None
        self._fitting: set[str] = set()

        self.rows = W.VBox()
        self.note = W.HTML()
        self.no_fitting = W.HTML()
        self.btn_add = W.Button(
            description="Add measurement for this step", icon="upload",
            button_style="primary", layout=W.Layout(width="auto", display="none"),
        )
        self.btn_add.on_click(lambda _b: self._on_add and self._on_add())

    def selected_names(self) -> List[str]:
        """Return the names of the ticked measurements."""
        return [name for name, box in self.boxes.items() if box.value]

    def selected(self) -> List[Comparison]:
        """Return the ticked measurements, resolved against the study."""
        by_name = {c.name: c for c in self._study.comparisons}
        return [by_name[n] for n in self.selected_names() if n in by_name]

    def _toggled(self, change: Any) -> None:
        name = next(n for n, box in self.boxes.items() if box is change["owner"])
        if name in self._fitting:
            (self.excluded.discard if change["new"] else self.excluded.add)(name)
        self._on_toggle()

    def refresh(
        self,
        guide: Optional[ChainStepGuide],
        selected: Optional[List[str]] = None,
        *,
        auto_include: bool = False,
        syncing: bool = False,
        disabled: bool = False,
    ) -> List[str]:
        """Rebuild the rows, keeping (or setting) the selection; return measurements added.

        A chain step lists only the measurements whose experiment type feeds it, plus
        selected ones that do not fit (with a warning); a custom step lists all. Fitting
        measurements unselected when a chain step is first shown without recorded
        exclusions, or when the user (not `syncing`) switches it to another chain step,
        count as left out. With `auto_include`, fitting measurements not left out are
        selected.
        """
        if selected is None:
            selected = self.selected_names()
        guide_id = guide.id if guide is not None else None
        added: List[str] = []
        if guide is None:
            shown = list(self._study.comparisons)
            fitting_names: set[str] = {c.name for c in shown}
        else:
            fitting = [
                c for c in self._study.comparisons if c.experiment_type in guide.experiment_types
            ]
            fitting_names = {c.name for c in fitting}
            if self.excluded is None or (guide_id != self.rows_guide and not syncing):
                self.excluded = (self.excluded or set()) | (fitting_names - set(selected))
            if auto_include:
                added = [
                    c.name for c in fitting
                    if c.name not in self.excluded and c.name not in selected
                ]
                selected = [*selected, *added]
            shown = [
                c for c in self._study.comparisons
                if c.name in fitting_names or c.name in selected
            ]
        self.rows_guide = guide_id
        self._fitting = fitting_names if guide is not None else set()

        rows, self.boxes = [], {}
        for comparison in shown:
            box = W.Checkbox(
                value=comparison.name in selected, indent=False,
                layout=W.Layout(width="auto"), disabled=disabled,
            )
            box.observe(self._toggled, names="value")
            self.boxes[comparison.name] = box
            problems = self._study.measurement_problems(comparison)
            chip = (
                status_html("warn", f"{len(problems)} problem(s): " + " ".join(problems))
                if problems else status_html("ok", "ready")
            )
            detail = html.escape(measurement_caption(comparison))
            children = [
                box,
                W.HTML(f"<b>{html.escape(comparison.name)}</b> <small>{detail}</small>"),
                W.HTML(chip),
            ]
            if comparison.name not in fitting_names:
                children.append(W.HTML(_does_not_fit_html(comparison)))
            rows.append(W.HBox(children, layout=W.Layout(align_items="center")))
        if not rows and guide is None:
            rows = [W.HTML("<em>No measurements in this study yet.</em>")]
        self.rows.children = rows

        if guide is None:
            self.note.value = ""
            self.no_fitting.value = ""
        else:
            self.note.value = (
                "<small>Measurements whose experiment type feeds this step. All are "
                "included; untick one to leave it out (e.g. a bad replicate). New ones "
                "are included when you add them.</small>"
            )
            labels = ", ".join(EXPERIMENT_TYPES[t].label for t in guide.experiment_types)
            self.no_fitting.value = "" if fitting_names else status_html(
                "warn", f"No measurement fits this step yet. It needs: {labels}."
            )
        show_add = guide is not None and not fitting_names and self._on_add
        self.btn_add.layout.display = "" if show_add else "none"
        return added

    def excluded_names(self) -> Optional[tuple]:
        """Return the measurements left out, in study order, or None if never recorded."""
        if self.excluded is None:
            return None
        return tuple(c.name for c in self._study.comparisons if c.name in self.excluded)

    def set_locked(self, locked: bool) -> None:
        """Make the tick boxes read-only (or editable again)."""
        for box in self.boxes.values():
            box.disabled = locked
