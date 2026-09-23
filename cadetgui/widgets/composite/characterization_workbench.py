from __future__ import annotations

from typing import Dict, Optional, Sequence

import ipywidgets as W

from ...cadetprocessadapter import BINDING_MODELS, COLUMN_MODELS
from .._chrome import logo_data_uri, style_tag
from .._sidebar_shell import SidebarShell, collect_panes, validate_steps
from .characterization import CharacterizationWidget
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget

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
_STEPS = ("System", "Configuration") + _STAGE_STEPS


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

        self._stages: Dict[str, CharacterizationWidget] = {}
        stage_factories = {
            "Periphery: pre-injection": lambda: CharacterizationWidget(
                "periphery", config=self.configuration, instrument=self.instrument,
                tubing_unit="tubing_pre_injection",
            ),
            "Periphery: detectors": lambda: CharacterizationWidget(
                "periphery", config=self.configuration, instrument=self.instrument,
                tubing_unit="tubing_detectors",
            ),
            "Periphery: pre-injection + mixer": lambda: CharacterizationWidget(
                "pre_injection", config=self.configuration, instrument=self.instrument,
            ),
            "Bed": lambda: CharacterizationWidget("bed", config=self.configuration),
            "Particles": lambda: CharacterizationWidget("particles", config=self.configuration),
            "Adsorption": lambda: CharacterizationWidget("adsorption", config=self.configuration),
            "Capacity": lambda: CharacterizationWidget("capacity", config=self.configuration),
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
            },
        )
        self._shell = SidebarShell(panes)
        self._nav = self._shell.nav

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Characterization</span>"
            "</div>"
        )

        self.root = W.VBox([W.HTML(style_tag()), top_bar, self._shell.body])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-workbench")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
