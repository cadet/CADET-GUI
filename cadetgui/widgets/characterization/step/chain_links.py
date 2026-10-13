"""The chain links of a step setup: values it needs from earlier steps and what it determines."""

from __future__ import annotations

import html
from typing import Any, Callable, List

import ipywidgets as W

from ....characterization.guide import parameter_label
from ....characterization.runner import StepSetup
from ....characterization.study import Study


class ChainLinks:
    """Requirements picker and the "Uses / Determines" lines of a step."""

    def __init__(self, study: Study, on_change: Callable[[Any], None]) -> None:
        self._study = study
        self._syncing = False
        self._paths: List[str] = []
        self.provided: List[str] = []

        self.requires = W.SelectMultiple(
            description="Requires:", layout=W.Layout(width="100%", height="110px")
        )
        self.requires.observe(
            lambda change: None if self._syncing else on_change(change), names="value"
        )
        self.provides = W.HTML()
        self.line = W.HTML()
        self.box = W.VBox([
            W.HTML("<small>Values this step needs from earlier steps, and what it determines."
                   "</small>"),
            self.requires,
            self.provides,
        ])

    def refresh(self, setup: StepSetup) -> None:
        """Offer every declared path and every other step's outputs as requirements."""
        paths = set(self._study.initial_store.specs) | set(self._study.initial_store.entries)
        for step in self._study.steps:
            if step.name == setup.name:
                continue
            try:
                paths.update(step.provides)
            except ValueError:
                pass
        paths.update(setup.requires)
        options = sorted(paths)
        if self._paths != options:
            syncing, self._syncing = self._syncing, True
            kept = tuple(p for p in self.requires.value if p in options)
            self._paths = options
            self.requires.options = [(parameter_label(p), p) for p in options]
            self.requires.value = kept
            self._syncing = syncing

    def set_required(self, requires: Any) -> None:
        """Select the offered paths among `requires`."""
        self.requires.value = tuple(p for p in requires if p in self._paths)

    def show(self, provides: List[str], guided: bool) -> None:
        """Show what the step uses and determines; the one-line summary only when `guided`."""
        self.provided = list(provides)

        def names(paths: Any) -> str:
            return ", ".join(html.escape(parameter_label(p)) for p in paths) or "nothing"

        self.provides.value = f"<small>Determines: {names(provides)}</small>"
        self.line.value = (
            f"<small>Uses from earlier steps: {names(self.requires.value)} · "
            f"Determines: {names(provides)}</small>"
        ) if guided else ""
