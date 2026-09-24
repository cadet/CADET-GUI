from __future__ import annotations

from typing import Dict, Optional, Sequence

import ipywidgets as W

from ...cadetprocessadapter import BINDING_MODELS, COLUMN_MODELS
from .._chrome import logo_data_uri, style_tag
from .._sidebar_shell import SidebarShell, collect_panes, validate_steps
from .characterization import CharacterizationWidget
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget
from .parameter_history import ParameterHistoryWidget, ParameterPushRecord

__all__ = ["CharacterizationWorkbenchWidget"]

_STAGE_STEPS = (
    "Periphery: pre-injection",
    "Periphery: detectors",
    "Periphery: pre-injection + mixer",
    "Bed",
    "Particles",
    "Adsorption",
    "Capacity",
)
_STEPS = ("System", "Configuration") + _STAGE_STEPS + ("History",)


class CharacterizationWorkbenchWidget:
    """Same top-bar/sidebar shell as `WorkbenchWidget`, one pane per characterization stage.

    Same wiring pattern as `WorkbenchWidget` (widgets/composite/workbench.py):
    a shared `InstrumentWidget`/`ConfigurationWidget`, one `(label, widget)`
    pane per step under `SidebarShell`, `include=` narrows which panes are
    shown. Deliberately a *separate* class rather than another
    `WorkbenchWidget` step -- characterization overlaps conceptually with
    `ParameterEstimationWidget` and the main workbench stays manual/free-flow.

    Every stage pane shares the *same* `.instrument`/`.configuration` --
    each stage's own "Accept fitted parameters" writes straight into their
    live form fields, so a later stage's pane already sees an earlier
    stage's accepted result, in-memory, no explicit hand-off needed.

    Unlike `WorkbenchWidget`'s four independent steps, `instrument`/
    `configuration` are always built regardless of `include=` (every stage
    pane needs both to exist, even when its own pane isn't shown) --
    `include=` only ever controls which panes actually render.

    A default-constructed `instrument`/`configuration` (i.e. neither is
    passed in) is seeded so every stage pane works out of the box: "Use LC
    system" on with the periphery-relevant units included (needed for the
    two "Periphery: ..." panes to have anything to fit), and a column/
    binding pair with pores and a capacity/characteristic-charge (LRMP +
    SMA) rather than `ConfigurationWidget`'s own bare LRM/Linear default,
    which has neither `bed_porosity` nor `capacity`/`characteristic_charge`
    for "Bed"/"Adsorption"/"Capacity" to fit. Passing in an already-built
    `instrument`/`configuration` skips all of that -- whatever state it's
    already in is left alone.
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
            self.instrument = InstrumentWidget()
            self.instrument._use_lc_system_checkbox.value = True
            for unit in ("tubing_pre_injection", "tubing_detectors", "mixer"):
                self.instrument._unit_checkboxes[unit].value = True

        self.configuration = configuration
        if self.configuration is None:
            self.configuration = ConfigurationWidget(instrument=self.instrument)
            self.configuration._column_picker.value = COLUMN_MODELS[
                "Lumped Rate Model With Pores (LRMP)"
            ]
            self.configuration._binding_picker.value = BINDING_MODELS[
                "Steric Mass Action (SMA)"
            ]

        # Shared across every stage pane -- each stage's "Push to
        # Configuration" records here too, so "History" sees every push
        # made from any pane, in order.
        self.history = ParameterHistoryWidget()
        self.history.add_reapply_listener(self._on_reapply)

        self._stages: Dict[str, CharacterizationWidget] = {}
        stage_factories = {
            "Periphery: pre-injection": lambda: CharacterizationWidget(
                "periphery", config=self.configuration, instrument=self.instrument,
                history=self.history, tubing_unit="tubing_pre_injection",
            ),
            "Periphery: detectors": lambda: CharacterizationWidget(
                "periphery", config=self.configuration, instrument=self.instrument,
                history=self.history, tubing_unit="tubing_detectors",
            ),
            "Periphery: pre-injection + mixer": lambda: CharacterizationWidget(
                "pre_injection", config=self.configuration, instrument=self.instrument,
                history=self.history,
            ),
            "Bed": lambda: CharacterizationWidget(
                "bed", config=self.configuration, history=self.history,
            ),
            "Particles": lambda: CharacterizationWidget(
                "particles", config=self.configuration, history=self.history,
            ),
            "Adsorption": lambda: CharacterizationWidget(
                "adsorption", config=self.configuration, history=self.history,
            ),
            "Capacity": lambda: CharacterizationWidget(
                "capacity", config=self.configuration, history=self.history,
            ),
        }
        for name in _STAGE_STEPS:
            if name in steps:
                self._stages[name] = stage_factories[name]()

        panes = collect_panes(
            _STEPS,
            {
                "System": self.instrument.root if "System" in steps else None,
                "Configuration": self.configuration.root if "Configuration" in steps else None,
                **{name: widget.root for name, widget in self._stages.items()},
                "History": self.history.root if "History" in steps else None,
            },
        )
        self._shell = SidebarShell(panes)
        self._nav = self._shell.nav
        self._wire_status()

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Characterization</span>"
            "</div>"
        )

        self.root = W.VBox([W.HTML(style_tag()), top_bar, self._shell.body])
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

        if "Configuration" in self._shell.panes:
            self._shell.set_warning("Configuration", config_problem)
        for name, widget in self._stages.items():
            message = config_problem or (
                None if widget.data.datasets else "Load an experimental dataset first."
            )
            self._shell.set_warning(name, message)

    def _on_reapply(self, push: ParameterPushRecord) -> None:
        """Route a "Re-apply" click to whichever stage's own write_targets match.

        `push.stage` alone doesn't disambiguate: "Periphery: pre-injection"
        and "Periphery: detectors" both have `stage == "periphery"` but
        write back to different tubing units, so this matches on the
        pushed parameter *names* instead -- each stage's `write_targets`
        keys are a distinct set (e.g. `tubing_pre_injection_length` only
        ever belongs to the pre-injection pane), so exactly one stage's
        keys are ever a superset of a given push's.
        """
        for widget in self._stages.values():
            if set(push.values) <= set(widget._spec.write_targets):
                widget._write_fitted_values(push.values)
                return

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
