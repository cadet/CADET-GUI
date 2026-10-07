from __future__ import annotations

from typing import Optional, Sequence

from .._sidebar_shell import (
    SYSTEM_GROUP,
    SidebarShell,
    collect_panes,
    resolve_step,
    system_pane_label,
    validate_steps,
)
from ._bench import bench_root
from .configuration import ConfigurationWidget
from .instrument import InstrumentWidget
from .parameter_estimation import ParameterEstimationWidget
from .solution import SolutionWidget

__all__ = ["WorkbenchWidget"]

SYSTEM = SYSTEM_GROUP
PROCESS = "Process configuration"
SIMULATION = "Simulation"
ESTIMATION = "Parameter Estimation"
SYSTEM_PANE = system_pane_label("Instrument")
PROCESS_PANE = system_pane_label(PROCESS)
_STEPS = (SYSTEM, PROCESS, SIMULATION, ESTIMATION)


class WorkbenchWidget:
    """Top-level shell: a sidebar of system and process configuration, simulation, estimation.

    Builds and wires an `InstrumentWidget`, `ConfigurationWidget`, `SolutionWidget` and
    `ParameterEstimationWidget`, showing one at a time via `SidebarShell`. Each stays a plain
    attribute (`.instrument`/`.configuration`/`.solution`/`.parameter_estimation`). The
    instrument and the process configuration are the "System" group's sub-panes
    ("System: Instrument", "System: Process configuration"), as in the characterization
    workbench.

    `include` narrows which steps are built and shown (default: all of `_STEPS`); a
    skipped step is neither constructed nor wired. Passing an explicit widget for a step
    not in `include` raises `ValueError`.
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
            SYSTEM,
            instrument,
            steps=steps,
            factory=lambda: InstrumentWidget(hardware_expanded=False),
        )
        self.configuration = resolve_step(
            PROCESS,
            configuration,
            steps=steps,
            factory=lambda: ConfigurationWidget(workspace_header=False),
        )
        self.solution = resolve_step(SIMULATION, solution, steps=steps, factory=SolutionWidget)
        self.parameter_estimation = resolve_step(
            ESTIMATION,
            parameter_estimation,
            steps=steps,
            factory=ParameterEstimationWidget,
        )

        if self.parameter_estimation is not None:
            self.parameter_estimation.auto_preview = False

        if self.instrument is not None and self.configuration is not None:
            self.configuration.bind_to_instrument(self.instrument)

        if self.configuration is not None:
            for dependent in (self.solution, self.parameter_estimation):
                if dependent is not None:
                    dependent.bind_to_config(self.configuration)

        panes = collect_panes(
            (SYSTEM_PANE, PROCESS_PANE, SIMULATION, ESTIMATION),
            {
                SYSTEM_PANE: self.instrument.root if self.instrument else None,
                PROCESS_PANE: self.configuration.root if self.configuration else None,
                SIMULATION: self.solution.root if self.solution else None,
                ESTIMATION: (
                    self.parameter_estimation.root if self.parameter_estimation else None
                ),
            },
        )
        self._shell = SidebarShell(panes, groups={SYSTEM: [SYSTEM_PANE, PROCESS_PANE]})
        if self.parameter_estimation is not None:
            estimation = self.parameter_estimation
            self._shell.add_show_listener(
                lambda label: estimation.refresh_preview() if label == ESTIMATION else None
            )

        self.root = bench_root("Workbench", self._shell, self.configuration)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
