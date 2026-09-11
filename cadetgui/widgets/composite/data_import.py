from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import ipywidgets as W
import numpy as np

from .._chrome import style_tag
from ..elements import ChoiceField

__all__ = ["DataImportWidget", "ExperimentalDataset"]


@dataclass
class ExperimentalDataset:
    """One imported experimental signal, time already normalized to minutes."""

    label: str
    time_min: np.ndarray
    signal: np.ndarray


def _parse_csv(content: bytes) -> Tuple[np.ndarray, np.ndarray]:
    """Parse (time, signal) from a CSV's first two columns, skipping the header row."""
    text = content.decode("utf-8", errors="replace")
    times: List[float] = []
    values: List[float] = []
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) < 2:
            continue
        try:
            times.append(float(row[0]))
            values.append(float(row[1]))
        except ValueError:
            continue
    return np.array(times), np.array(values)


class DataImportWidget:
    """Import experimental chromatography data (CSV: time, signal) for comparison.

    Assumes a header row and uses the file's first two columns as time/signal —
    full column mapping (PRODUCT_VISION.md §13) is bigger scope, not built yet.
    `SolutionWidget.bind_to_data()` overlays loaded datasets on its plot.
    """

    def __init__(self) -> None:
        self.datasets: List[ExperimentalDataset] = []
        self._listeners: List[Callable[[], None]] = []

        self._upload = W.FileUpload(accept=".csv", multiple=True, description="Import CSV")
        self._time_unit = ChoiceField(
            label="Time column is in:",
            options=[("minutes", "min"), ("seconds", "s")],
        )
        self._dataset_picker = ChoiceField(label="Loaded:", options=[])
        self._btn_remove = W.Button(description="Remove", icon="trash")
        self._preview_out = W.Output()
        self.status = W.HTML("<em>No experimental data loaded.</em>")
        self.status.add_class("cadetgui-status")

        self._upload.observe(self._on_upload, names="value")
        self._btn_remove.on_click(self._on_remove)
        self._dataset_picker.observe(self._on_pick, names="selected_index")

        toolbar = W.HBox(
            [self._upload, self._time_unit, self._dataset_picker, self._btn_remove],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Experimental data</div>"),
                toolbar,
                self._preview_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Register a callback fired (no args) whenever the dataset list changes."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    def _on_upload(self, change: dict) -> None:
        if change.get("name") != "value" or not self._upload.value:
            return
        for item in self._upload.value:
            name = item["name"]
            time, signal = _parse_csv(bytes(item["content"]))
            if time.size == 0:
                self.status.value = f"<span style='color:#b00020'>Could not parse {name}.</span>"
                continue
            if self._time_unit.value == "s":
                time = time / 60.0
            label = name.rsplit(".", 1)[0]
            self.datasets.append(ExperimentalDataset(label=label, time_min=time, signal=signal))
            self.status.value = f"<em>Loaded {label} ({time.size} points).</em>"

        self._dataset_picker.set_options([(d.label, d) for d in self.datasets], keep_value=False)
        if self.datasets:
            self._dataset_picker.selected_index = len(self.datasets) - 1
        self._upload.value = ()  # allow re-uploading the same filename later
        self._preview_selected()
        self._notify()

    def _on_remove(self, _btn: object) -> None:
        ds = self._dataset_picker.value
        if ds is None:
            return
        self.datasets.remove(ds)
        self._dataset_picker.set_options([(d.label, d) for d in self.datasets])
        self._preview_out.clear_output()
        self.status.value = f"<em>Removed {ds.label}.</em>"
        self._notify()

    def _on_pick(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._preview_selected()

    def _preview_selected(self) -> None:
        ds: Optional[ExperimentalDataset] = self._dataset_picker.value
        self._preview_out.clear_output(wait=True)
        if ds is None:
            return
        with self._preview_out:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, ax = plt.subplots(figsize=(5, 3))
            ax.plot(ds.time_min, ds.signal)
            ax.set_xlabel("Time / min")
            ax.set_ylabel("Signal")
            ax.set_title(ds.label)
            display(fig)
            plt.close(fig)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
