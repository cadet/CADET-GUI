"""The optimizer of a step setup: choice, size knobs and the estimated simulation count."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List

import ipywidgets as W

from ....characterization.runner import (
    DEFAULT_OPTIMIZER,
    default_optimizer,
    default_optimizer_knobs,
    estimated_simulations,
)
from ....estimation.optimizer_runner import OPTIMIZERS
from ...elements import ChoiceField

MULTI_OBJECTIVE = DEFAULT_OPTIMIZER


def _knob_tooltip(is_population_based: bool) -> str:
    text = "Pre-filled from the number of fitted variables until you change it."
    if is_population_based:
        text += " 0 lets CADET-Process size it (large: can take hours)."
    return text


class OptimizerSettings:
    """Optimizer choice and knobs; knobs the user has not edited follow the fitted variables."""

    def __init__(
        self,
        n_fitted: Callable[[], int],
        n_measurements: Callable[[], int],
        on_change: Callable[[], None],
    ) -> None:
        self._n_fitted = n_fitted
        self._n_measurements = n_measurements
        self._on_change = on_change
        self._syncing = False
        self._edited_knobs: set[tuple[str, str]] = set()

        self.optimizer = ChoiceField(
            label="Optimizer:", options=[(name, name) for name in OPTIMIZERS]
        )
        self.optimizer.value = MULTI_OBJECTIVE
        self.estimate = W.HTML()
        self.knob_fields: Dict[str, List[W.IntText]] = {
            name: [
                W.IntText(
                    value=k.default, description=k.label,
                    tooltip=_knob_tooltip(spec.is_population_based),
                )
                for k in spec.knobs
            ]
            for name, spec in OPTIMIZERS.items()
        }
        self.knob_boxes = {
            name: W.HBox(fields, layout=W.Layout(flex_flow="row wrap"))
            for name, fields in self.knob_fields.items()
        }

        self.optimizer.observe(self._on_optimizer_change, names="selected_index")
        for name, spec in OPTIMIZERS.items():
            for knob, knob_field in zip(spec.knobs, self.knob_fields[name]):
                knob_field.observe(
                    lambda _c, key=(name, knob.attr): self._on_knob_edit(key), names="value"
                )

        self.controls = W.HBox(
            [self.optimizer, *self.knob_boxes.values()], layout=W.Layout(flex_flow="row wrap"),
        )

    def _on_knob_edit(self, key: tuple[str, str]) -> None:
        if self._syncing:
            return
        self._edited_knobs.add(key)
        self.update_estimate()
        self._on_change()

    def _on_optimizer_change(self, _change: Any) -> None:
        selected = self.optimizer.value
        for name, box in self.knob_boxes.items():
            box.layout.display = "" if name == selected else "none"
        self.update_estimate()
        if not self._syncing:
            self._on_change()

    def prefill(self) -> None:
        """Set every knob the user has not edited to its size for the fitted variables."""
        syncing, self._syncing = self._syncing, True
        try:
            n = self._n_fitted()
            for name, spec in OPTIMIZERS.items():
                sized = default_optimizer_knobs(name, n)
                for knob, knob_field in zip(spec.knobs, self.knob_fields[name]):
                    if (name, knob.attr) not in self._edited_knobs:
                        knob_field.value = sized[knob.attr]
        finally:
            self._syncing = syncing
        self.update_estimate()

    def update_estimate(self) -> None:
        """Show roughly how many simulations the run takes."""
        n_comparisons = self._n_measurements()
        settings = self.settings()
        count = estimated_simulations(settings, n_comparisons)
        measurements = f"{n_comparisons} measurement{'s' if n_comparisons != 1 else ''}"
        if settings["name"] == MULTI_OBJECTIVE and count is None:
            text = (
                "Population size or generations 0: CADET-Process sizes the run itself, "
                "which can take hours."
            )
        elif settings["name"] == MULTI_OBJECTIVE:
            knobs = settings["knobs"]
            text = (
                f"≈ {count:,} simulations ({knobs['pop_size']} × {knobs['n_max_gen']} "
                f"generations × {measurements})."
            )
        elif count is not None:
            text = (
                f"≈ {count:,} simulations (max iterations × {measurements}; approximate, "
                "scipy's evaluations per iteration vary)."
            )
        else:
            text = ""
        self.estimate.value = f"<small>{html.escape(text)}</small>" if text else ""

    def set_settings(self, optimizer: dict) -> None:
        """Show `optimizer`; its knobs that differ from the sized defaults count as edited."""
        syncing, self._syncing = self._syncing, True
        try:
            name = optimizer.get("name", MULTI_OBJECTIVE)
            sized = default_optimizer_knobs(name, self._n_fitted())
            self._edited_knobs = set()
            for knob, knob_field in zip(OPTIMIZERS[name].knobs, self.knob_fields[name]):
                knob_field.value = int(optimizer.get("knobs", {}).get(knob.attr, knob.default))
                if knob_field.value != sized[knob.attr]:
                    self._edited_knobs.add((name, knob.attr))
            self.optimizer.value = name
        finally:
            self._syncing = syncing
        self.sync_choices()

    def sync_choices(self) -> None:
        """Offer single-objective optimizers only for one measurement."""
        syncing, self._syncing = self._syncing, True
        try:
            allowed = list(OPTIMIZERS) if self._n_measurements() == 1 else [MULTI_OBJECTIVE]
            current = self.optimizer.value
            self.optimizer.set_options([(name, name) for name in allowed])
            self.optimizer.value = current if current in allowed else MULTI_OBJECTIVE
            self._on_optimizer_change(None)
        finally:
            self._syncing = syncing

    def settings(self) -> dict:
        """Return the chosen optimizer as `StepSetup.optimizer`."""
        name = self.optimizer.value
        knobs = OPTIMIZERS[name].knobs
        return default_optimizer(
            name, **{k.attr: int(f.value) for k, f in zip(knobs, self.knob_fields[name])}
        )

    def set_locked(self, locked: bool) -> None:
        """Make the choice and the knobs read-only (or editable again)."""
        self.optimizer.disabled = locked
        for fields in self.knob_fields.values():
            for field in fields:
                field.disabled = locked
