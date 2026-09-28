from __future__ import annotations

from typing import Optional, Sequence

import ipywidgets as W

from .._chrome import logo_data_uri, style_tag
from .._sidebar_shell import SidebarShell, collect_panes, resolve_step, validate_steps
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget
from .parameter_estimation import ParameterEstimationWidget
from .solution import SolutionWidget
from .workspace_header import hoisted_header_rows

__all__ = ["WorkbenchWidget"]

_STEPS = ("System Configuration", "Process Configuration", "Simulation", "Parameter Estimation")


class WorkbenchWidget:
    """Top-level shell: a sidebar of system and process configuration, simulation, estimation.

    Builds and wires an `InstrumentWidget`, `ConfigurationWidget`, `SolutionWidget` and
    `ParameterEstimationWidget`, showing one at a time via `SidebarShell`. Each stays a plain
    attribute (`.instrument`/`.configuration`/`.solution`/`.parameter_estimation`).

    `include` narrows which steps are built and shown (default: all four); a skipped step is
    neither constructed nor wired. Passing an explicit widget for a step not in `include`
    raises `ValueError`.
    """

    def __init__(
        self,
        *,
        include: Optional[Sequence[str]] = None,
        instrument: Optional[InstrumentWidget] = None,
        configuration: Optional[ConfigurationWidget] = None,
        solution: Optional[SolutionWidget] = None,
        parameter_estimation: Optional[ParameterEstimationWidget] = None,
    ) -> None:
        steps = tuple(include) if include is not None else _STEPS
        validate_steps(steps, _STEPS)

        self.instrument = resolve_step(
            "System Configuration",
            instrument,
            steps=steps,
            factory=lambda: InstrumentWidget(hardware_expanded=False),
        )
        self.configuration = resolve_step(
            "Process Configuration",
            configuration,
            steps=steps,
            factory=lambda: ConfigurationWidget(workspace_header=False),
        )
        self.solution = resolve_step(
            "Simulation", solution, steps=steps, factory=SolutionWidget
        )
        self.parameter_estimation = resolve_step(
            "Parameter Estimation",
            parameter_estimation,
            steps=steps,
            factory=ParameterEstimationWidget,
        )

        if self.instrument is not None and self.configuration is not None:
            self.configuration.bind_to_instrument(self.instrument)

        if self.configuration is not None:
            for dependent in (self.solution, self.parameter_estimation):
                if dependent is not None:
                    dependent.bind_to_config(self.configuration)

        panes = collect_panes(
            _STEPS,
            {
                "System Configuration": self.instrument.root if self.instrument else None,
                "Process Configuration": self.configuration.root if self.configuration else None,
                "Simulation": self.solution.root if self.solution else None,
                "Parameter Estimation": (
                    self.parameter_estimation.root if self.parameter_estimation else None
                ),
            },
        )
        self._shell = SidebarShell(panes)

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Workbench</span>"
            "</div>"
        )

        header_rows = hoisted_header_rows(self.configuration)
        self.root = W.VBox([W.HTML(style_tag()), top_bar, *header_rows, self._shell.body])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-workbench")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
