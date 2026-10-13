"""Choice among the experiment types of the chain step a measurement is added for."""

from __future__ import annotations

import html
from typing import Callable, Optional

import ipywidgets as W

from ....characterization.guide import CHAIN_BY_ID, EXPERIMENT_TYPES
from .labels import detector_hint

__all__ = ["StepTypeChoice"]


class StepTypeChoice:
    """Radio buttons over a fixed step's types, preselected once per channel by its detector.

    `on_choose(type_id)` is called when the user picks a type.
    """

    def __init__(self, on_choose: Callable[[str], None]) -> None:
        self._on_choose = on_choose
        self.step: Optional[str] = None
        self._explicit: Optional[str] = None
        self._default: Optional[str] = None
        self._typed_for_channel: Optional[str] = None
        self._chosen = False
        self._loading = False
        self.radio = W.RadioButtons(layout=W.Layout(width="auto"))
        self.radio.add_class("cadetgui-step-type")
        self.info = W.HTML()
        self.root = W.VBox([self.info, self.radio], layout=W.Layout(display="none"))
        self.radio.observe(self._on_radio, names="value")

    def reset(
        self, step: Optional[str], *, explicit: Optional[str], default: Optional[str]
    ) -> None:
        """Offer `step`'s types (none: hidden); `explicit` wins over the detector."""
        self.step, self._explicit, self._default = step, explicit, default
        self._typed_for_channel = None
        self._chosen = False
        self.root.layout.display = "" if step is not None else "none"

    def preselect(self, channel: Optional[str]) -> Optional[str]:
        """Return the type to select for a newly picked `channel`, else None."""
        if self.step is None or self._chosen or channel == self._typed_for_channel:
            return None
        self._typed_for_channel = channel
        types = list(CHAIN_BY_ID[self.step].experiment_types)
        hint = detector_hint(channel or "")
        matches = [t for t in types if EXPERIMENT_TYPES[t].detector == hint]
        if self._explicit in types:
            return self._explicit
        return matches[0] if len(matches) == 1 else (self._default or types[0])

    def show(self, selected: Optional[str]) -> None:
        """Show the step's types with `selected` picked."""
        if self.step is None:
            return
        types = list(CHAIN_BY_ID[self.step].experiment_types)
        self._loading = True
        try:
            self.radio.options = [(EXPERIMENT_TYPES[t].label, t) for t in types]
            self.radio.value = selected
        finally:
            self._loading = False
        self.radio.layout.display = "" if len(types) > 1 else "none"
        if len(types) == 1:
            experiment_type = EXPERIMENT_TYPES[types[0]]
            self.info.value = (
                f"<p><b>Experiment:</b> {html.escape(experiment_type.label)} — what you run: "
                f"{html.escape(experiment_type.what_you_run)}</p>"
            )
            return
        lines = "".join(
            f"<li><b>{html.escape(EXPERIMENT_TYPES[t].label)}</b>: "
            f"{html.escape(EXPERIMENT_TYPES[t].what_you_run)}</li>"
            for t in types
        )
        self.info.value = (
            "<p><b>Which experiment did you run?</b> Preselected from the channel's "
            f"detector where it tells them apart.</p><ul class='cadetgui-note'>{lines}</ul>"
        )

    def _on_radio(self, change: dict) -> None:
        if self._loading or change["new"] is None:
            return
        self._chosen = True
        self._on_choose(change["new"])
