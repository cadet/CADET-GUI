# =========================================
# File: cadetgui/widgets/composite/solution.py
# =========================================
from __future__ import annotations

from typing import Any, Callable, Optional

import ipywidgets as W

from ...simulation import run_process as _default_runner
from ..elements import ChoiceField

__all__ = ["SolutionWidget"]


class SolutionWidget:
    """Run a CADET-Process process and plot its solution.

    Plots via `SolutionIO.plot()` directly (CADET-Process already provides it —
    see ai-docs/ARCHITECTURE.md's "no duplicated numerical engine" principle).
    """

    def __init__(
        self,
        *,
        process: Any = None,
        runner: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._runner = runner or _default_runner
        self.process = process
        self.result: Any = None

        self._process_label = W.HTML()
        self._btn_run = W.Button(description="Run simulation", icon="play", button_style="success")
        self._btn_clear = W.Button(description="Clear", icon="trash")
        self._signal_picker = ChoiceField(label="Signal:", options=[])
        self._plot_out = W.Output()
        self.status = W.HTML("<em>Ready.</em>")

        self._btn_run.on_click(self._on_run)
        self._btn_clear.on_click(self._on_clear)
        self._signal_picker.observe(self._on_signal_change, names="selected_index")

        self.root = W.VBox(
            [
                W.HTML("<h3 style='margin:0'>Solution</h3>"),
                W.HBox([self._process_label, self._btn_run, self._btn_clear]),
                self._signal_picker,
                self._plot_out,
                self.status,
            ]
        )
        self._update_process_label()

    def set_process(self, process: Any) -> None:
        """Set the process to run on the next Run click."""
        self.process = process
        self._update_process_label()

    def bind_to_config(self, config_widget: Any) -> None:
        """Track a ConfigurationWidget's built process automatically."""
        config_widget.add_listener(self.set_process)
        if getattr(config_widget, "process", None) is not None:
            self.set_process(config_widget.process)

    def _update_process_label(self) -> None:
        if self.process is None:
            self._process_label.value = "<em>No process set.</em>"
        else:
            name = getattr(self.process, "name", type(self.process).__name__)
            self._process_label.value = f"<strong>Process:</strong> {name}"

    def _on_run(self, _btn: Any) -> None:
        self._plot_out.clear_output()
        if self.process is None:
            self.status.value = "<span style='color:#b00020'>No process to run.</span>"
            return
        try:
            self.result = self._runner(self.process)
        except Exception as exc:  # noqa: BLE001
            self.result = None
            self.status.value = f"<span style='color:#b00020'>Simulation failed: {exc}</span>"
            return

        signals = [
            (f"{unit}: {port}", (unit, port))
            for unit, ports in self.result.solution.items()
            for port in ports
        ]
        self._signal_picker.set_options(signals, keep_value=True)
        self.status.value = "<em>Simulation finished.</em>"
        self._plot_selected()

    def _on_clear(self, _btn: Any) -> None:
        self._plot_out.clear_output()
        self.result = None
        self._signal_picker.set_options([])
        self.status.value = "<em>Cleared.</em>"

    def _on_signal_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._plot_selected()

    def _plot_selected(self) -> None:
        if self.result is None or self._signal_picker.value is None:
            return
        unit, port = self._signal_picker.value
        solution = self.result.solution[unit][port]

        self._plot_out.clear_output(wait=True)
        with self._plot_out:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, _ax = solution.plot()
            display(fig)
            plt.close(fig)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
