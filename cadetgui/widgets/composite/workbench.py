from __future__ import annotations

from typing import Optional, Sequence

import ipywidgets as W

from .._chrome import logo_data_uri, style_tag
from .._sidebar_shell import SidebarShell, collect_panes, resolve_step, validate_steps
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget
from .parameter_estimation import ParameterEstimationWidget
from .solution import SolutionWidget

__all__ = ["WorkbenchWidget"]

_STEPS = ("System", "Configuration", "Simulation", "Parameter Estimation")


class WorkbenchWidget:
    """Top-level shell: a sidebar-navigated System/Configuration/Simulation/Estimation page.

    Builds and wires an `InstrumentWidget`, `ConfigurationWidget`,
    `SolutionWidget`, and `ParameterEstimationWidget` together (same bindings
    as examples/configuration_and_solution.ipynb), showing exactly one at a
    time via `SidebarShell` (`widgets/_sidebar_shell.py`) instead of stacking
    all four inline. Each stays a plain attribute
    (`.instrument`/`.configuration`/`.solution`/`.parameter_estimation`) for
    scripting — this class is purely "the known widgets, pre-wired, in a
    sidebar," not a black box; a different combination of widgets is a
    different `SidebarShell` call, not a change to this class. The "System"
    step (an `InstrumentWidget`, still `.instrument` on this class -- see
    REQUIREMENTS.md item #32 for why only the user-facing label changed) is
    optional layered-on-top topology, not a precondition: `ConfigurationWidget`
    already builds a standalone simulation on its own without one bound.

    `include` narrows which steps are built and shown at all (default: all
    four) — e.g. `WorkbenchWidget(include=("Configuration", "Simulation"))`
    for a notebook that has no use for the System step or parameter
    estimation. Skipping a step also skips its own construction and its
    `bind_to_*` wiring, so it costs nothing (no widgets built, no listeners
    attached) rather than just being hidden. Passing an explicit widget for a
    step not in `include` is a contradiction and raises `ValueError` rather
    than silently dropping it.
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
            "System", instrument, steps=steps, factory=InstrumentWidget
        )
        self.configuration = resolve_step(
            "Configuration", configuration, steps=steps, factory=ConfigurationWidget
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
                "System": self.instrument.root if self.instrument else None,
                "Configuration": self.configuration.root if self.configuration else None,
                "Simulation": self.solution.root if self.solution else None,
                "Parameter Estimation": (
                    self.parameter_estimation.root if self.parameter_estimation else None
                ),
            },
        )
        self._shell = SidebarShell(panes)
        self._nav = self._shell.nav  # exposed for scripting/tests, same name as before the split
        self._wire_status()

        top_bar = W.HTML(
            "<div class='cadetgui-topbar'>"
            f"<img src='{logo_data_uri()}' alt='CADET'>"
            "<span class='cadetgui-topbar-title'>Workbench</span>"
            "</div>"
        )

        self.root = W.VBox([W.HTML(style_tag()), top_bar, self._shell.body])
        self.root.add_class("cadetgui-panel")
        self.root.add_class("cadetgui-workbench")

    def _wire_status(self) -> None:
        if self.configuration is not None:
            self.configuration.add_listener(self._refresh_status)
        if self.parameter_estimation is not None:
            self.parameter_estimation.data.add_listener(self._refresh_status)
        self._refresh_status()

    def _refresh_status(self, *_args: object) -> None:
        """Flag steps that can't do anything useful yet, without blocking navigation."""
        config_problem = None
        if self.configuration is not None:
            config_problem = self.configuration.name_error("running a simulation")
            if config_problem is None and self.configuration.process is None:
                config_problem = "No valid process is built yet."

        warnings = {
            "Configuration": config_problem,
            "Simulation": config_problem,
            "Parameter Estimation": config_problem
            or (
                "Load an experimental dataset first."
                if self.parameter_estimation is not None
                and not self.parameter_estimation.data.datasets
                else None
            ),
        }
        for label, message in warnings.items():
            if label in self._shell.panes:
                self._shell.set_warning(label, message)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
