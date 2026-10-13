"""Channel page of the add-measurement stepper: pick and preview a detector channel."""

from __future__ import annotations

import html
from typing import Optional

import ipywidgets as W

from ....io.experimental_data import ExperimentalRun
from ...elements import ChoiceField, ChromatogramChart
from ...ui.layout import note, row
from .labels import reference_series

__all__ = ["ChannelPage"]


class ChannelPage:
    """The run's channels as a choice, the picked one's trace and the run-log markers."""

    def __init__(self) -> None:
        self.channel = ChoiceField(label="Channel:")
        self.chart = ChromatogramChart(view_width=480, view_height=200, y_label="Signal")
        self.markers = note()
        self.root = W.VBox([
            note("Pick the detector channel this measurement compares against."),
            row(self.channel),
            self.chart,
            self.markers,
        ])

    def fill(self, run: Optional[ExperimentalRun]) -> None:
        """Offer `run`'s channels, keeping the picked one where possible."""
        self.channel.set_options([(c, c) for c in (run.channels if run is not None else [])])

    def show(self, run: Optional[ExperimentalRun]) -> None:
        """Plot the picked channel of `run` and list its markers."""
        channel = self.channel.value
        if run is None or channel not in run.channels:
            self.chart.series = []
            return
        trace = run.channels[channel]
        volume = run.x_basis == "volume"
        self.chart.x_label = f"{'Volume' if volume else 'Time'} / {run.x_unit}"
        self.chart.x_name = "V" if volume else "t"
        self.chart.x_unit = run.x_unit
        self.chart.y_label = trace.unit or channel
        self.chart.series = [reference_series(channel, trace.x, trace.values)]
        self.markers.value = (
            "Markers found in the run log: " + ", ".join(
                html.escape(f"{text} @ {x:g} {run.x_unit}") for x, text in run.markers
            ) if run.markers else "No run-log markers in this file; the injection position "
            "can be entered by hand under Advanced after adding."
        )
