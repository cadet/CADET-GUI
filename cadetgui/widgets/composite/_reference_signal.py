from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ...cadetprocessadapter import measurable_signal_options
from ...parameter_estimation import (
    CalibrationMethod,
    build_reference,
    calibrate_reference,
)
from ..elements import ChoiceField

__all__ = ["ReferenceSignalControls"]


def _set_options_if_changed(picker: ChoiceField, options: List[tuple]) -> None:
    """Skip re-selecting when the labels are unchanged, so a deliberate pick survives."""
    if [label for label, _ in options] != picker.option_labels:
        picker.set_options(options, keep_value=True)


class ReferenceSignalControls:
    """Component/calibration/signal pickers shared by the estimation and characterization runners.

    Owns "Signal represents" (component), "Calibration" (with its Beer-Lambert/normalize
    fields) and "Signal" (measurable positions), and turns one dataset into a calibrated
    `Reference`. Callers compose the individual widgets into their own layout and call
    `refresh_signal_options`/`refresh_component_options` when the bound process changes.
    """

    def __init__(self, *, on_change: Optional[Callable[[], None]] = None) -> None:
        self._on_change = on_change
        self.component_picker = ChoiceField(label="Signal represents:", options=[])
        self.signal_picker = ChoiceField(label="Signal:", options=[])
        self.calibration_picker = ChoiceField(
            label="Calibration:",
            options=[
                ("None (raw signal)", "none"),
                ("Beer-Lambert (absorbance → concentration)", "beer_lambert"),
                ("Normalize by injected amount", "normalize_area"),
            ],
        )
        self.extinction_field = W.FloatText(value=1.0, description="Extinction coeff.:")
        self.path_length_field = W.FloatText(value=1.0, description="Path length (cm):")
        self.target_area_field = W.FloatText(value=1.0, description="Injected amount:")
        self.beer_lambert_box = W.HBox(
            [self.extinction_field, self.path_length_field], layout=W.Layout(display="none")
        )
        self.normalize_area_box = W.HBox(
            [self.target_area_field], layout=W.Layout(display="none")
        )
        self.calibration_picker.observe(self._on_calibration_change, names="selected_index")
        if on_change is not None:
            self.component_picker.observe(lambda _c: on_change(), names="selected_index")
            self.signal_picker.observe(lambda _c: on_change(), names="selected_index")
            for field in (self.extinction_field, self.path_length_field, self.target_area_field):
                field.observe(lambda _c: on_change(), names="value")

    def _on_calibration_change(self, _change: dict) -> None:
        method = self.calibration_picker.value
        self.beer_lambert_box.layout.display = "" if method == "beer_lambert" else "none"
        self.normalize_area_box.layout.display = "" if method == "normalize_area" else "none"
        if self._on_change is not None:
            self._on_change()

    def calibration_kwargs(self) -> Dict[str, float]:
        method = self.calibration_picker.value
        if method == "beer_lambert":
            return {
                "extinction_coefficient": self.extinction_field.value,
                "path_length": self.path_length_field.value,
            }
        if method == "normalize_area":
            return {"target_area": self.target_area_field.value}
        return {}

    def calibration_error(self) -> Optional[str]:
        method: CalibrationMethod = self.calibration_picker.value
        if method == "beer_lambert" and (
            self.extinction_field.value <= 0 or self.path_length_field.value <= 0
        ):
            return "Enter a positive extinction coefficient and path length."
        if method == "normalize_area" and self.target_area_field.value == 0:
            return "Enter a nonzero injected amount to normalize against."
        return None

    def reference_for(self, dataset: Any) -> Any:
        """Build the calibrated `Reference` for one `ExperimentalDataset`."""
        reference = build_reference(
            dataset.label, dataset.time_min, dataset.signal,
            component_name=self.component_picker.value,
        )
        return calibrate_reference(
            reference, self.calibration_picker.value, **self.calibration_kwargs()
        )

    def refresh_signal_options(self, process: Any) -> None:
        options = measurable_signal_options(process) if process is not None else []
        _set_options_if_changed(self.signal_picker, options)

    def refresh_component_options(self, components: List[str]) -> None:
        options = [(name, name) for name in components]
        options.append(("Total (sum of all components)", None))
        # "Total" and "nothing selected" are both None, so an unconditional set_options()
        # would bounce a deliberate "Total" pick back to the first component.
        _set_options_if_changed(self.component_picker, options)
