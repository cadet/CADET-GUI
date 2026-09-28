from __future__ import annotations

from typing import Dict, Optional, Sequence

import ipywidgets as W

from ...cadetprocessadapter import BINDING_MODELS, COLUMN_MODELS, INSTRUMENT_TEMPLATES
from .._chrome import logo_data_uri, style_tag
from .._sidebar_shell import SidebarShell, collect_panes, validate_steps
from .characterization import CharacterizationWidget
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget
from .parameter_history import ParameterHistoryWidget, ParameterPushRecord
from .workspace_header import hoisted_header_rows

__all__ = ["CharacterizationWorkbenchWidget"]

# Pane name -> (stage, tubing_unit).
_STAGE_PANES = {
    "Periphery: pre-injection": ("periphery", "tubing_pre_injection"),
    "Periphery: detectors": ("periphery", "tubing_detectors"),
    "Periphery: pre-injection + mixer": ("pre_injection", None),
    "Bed": ("bed", None),
    "Particles": ("particles", None),
    "Adsorption": ("adsorption", None),
    "Capacity": ("capacity", None),
}
_PERIPHERY_STEPS = tuple(name for name in _STAGE_PANES if name.startswith("Periphery"))
_SYSTEM = "System Configuration"
_PROCESS = "Process Configuration"
_STEPS = (_SYSTEM, _PROCESS, *_STAGE_PANES, "History")


class CharacterizationWorkbenchWidget:
    """Sidebar workbench with one `CharacterizationWidget` pane per stage.

    All stage panes share `.instrument`, `.configuration` and `.history`, so an accepted
    fit is visible to every later stage. Both are built even when `include=` hides
    their panes. When neither is passed in, they are seeded so every stage has something
    to fit: the periphery units, the Pulse Injection template, and an LRMP column with
    an SMA binding model. Passed-in instances are left as they are.
    """

    def __init__(
        self,
        *,
        include: Optional[Sequence[str]] = None,
        instrument: Optional[InstrumentWidget] = None,
        configuration: Optional[ConfigurationWidget] = None,
    ) -> None:
        steps = tuple(include) if include is not None else _STEPS
        validate_steps(steps, _STEPS)

        self.instrument = instrument
        if self.instrument is None:
            self.instrument = InstrumentWidget(hardware_expanded=True)
            for unit in ("tubing_pre_injection", "tubing_detectors", "mixer"):
                self.instrument._unit_checkboxes[unit].value = True

        self.configuration = configuration
        if self.configuration is None:
            self.configuration = ConfigurationWidget(
                instrument=self.instrument, workspace_header=False
            )
            self.configuration._model_picker.value = INSTRUMENT_TEMPLATES["Pulse Injection"]
            self.configuration._column_picker.value = COLUMN_MODELS[
                "Lumped Rate Model With Pores (LRMP)"
            ]
            self.configuration._binding_picker.value = BINDING_MODELS[
                "Steric Mass Action (SMA)"
            ]

        self.history = ParameterHistoryWidget()
        self.history.add_reapply_listener(self._on_reapply)

        self._stages: Dict[str, CharacterizationWidget] = {}
        for name, (stage, tubing_unit) in _STAGE_PANES.items():
            if name in steps:
                self._stages[name] = CharacterizationWidget(
                    stage, config=self.configuration, instrument=self.instrument,
                    history=self.history, tubing_unit=tubing_unit,
                )

        panes = collect_panes(
            _STEPS,
            {
                _SYSTEM: self.instrument.root if _SYSTEM in steps else None,
                _PROCESS: self.configuration.root if _PROCESS in steps else None,
                **{name: widget.root for name, widget in self._stages.items()},
                "History": self.history.root if "History" in steps else None,
            },
        )
        self._shell = SidebarShell(panes, groups={"Periphery": _PERIPHERY_STEPS})
        self._nav = self._shell.nav
        self._wire_status()

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Characterization</span>"
            "</div>"
        )

        header_rows = hoisted_header_rows(self.configuration)
        self.root = W.VBox([W.HTML(style_tag()), top_bar, *header_rows, self._shell.body])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-workbench")

    def _wire_status(self) -> None:
        self.configuration.add_listener(self._refresh_status)
        for widget in self._stages.values():
            widget.data.add_listener(self._refresh_status)
        self._refresh_status()

    def _refresh_status(self, *_args: object) -> None:
        """Flag steps that can't do anything useful yet, without blocking navigation."""
        config_problem = self.configuration.name_error("running a simulation")
        if config_problem is None and self.configuration.process is None:
            config_problem = "No valid process is built yet."

        if _PROCESS in self._shell.panes:
            self._shell.set_warning(_PROCESS, config_problem)
        for name, widget in self._stages.items():
            message = config_problem or (
                None if widget.data.datasets else "Load an experimental dataset first."
            )
            self._shell.set_warning(name, message)

    def _on_reapply(self, push: ParameterPushRecord) -> None:
        """Route a "Re-apply" click to the stage whose write targets cover the pushed names.

        Both periphery panes have `stage == "periphery"`, so the names decide.
        """
        for widget in self._stages.values():
            if set(push.values) <= set(widget._spec.write_targets):
                widget._write_fitted_values(push.values)
                return

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
