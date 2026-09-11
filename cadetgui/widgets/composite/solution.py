from __future__ import annotations

from typing import Any, Callable, Optional

import ipywidgets as W

from ...cadetprocessadapter import classify_signal_ports
from ...simulation import run_process as _default_runner
from .._chrome import style_tag
from ..elements import ChoiceField
from .run_history import RunHistoryWidget, RunRecord

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
        self._data_widget: Optional[Any] = None
        self._config_widget: Optional[Any] = None

        self._process_label = W.HTML()
        self._btn_run = W.Button(description="Run simulation", icon="play", button_style="success")
        self._btn_clear = W.Button(description="Clear", icon="trash")
        self._btn_load_config = W.Button(
            description="Load configuration", icon="upload",
            layout=W.Layout(display="none"),
        )
        self._signal_picker = ChoiceField(label="Signal:", options=[])
        self._plot_out = W.Output()
        self.status = W.HTML("<em>Ready.</em>")
        self.history = RunHistoryWidget()

        self._btn_run.on_click(self._on_run)
        self._btn_clear.on_click(self._on_clear)
        self._btn_load_config.on_click(self._on_load_config)
        self._signal_picker.observe(self._on_signal_change, names="selected_index")
        self.history.add_listener(self._on_history_pick)
        self.status.add_class("cadetgui-status")

        toolbar = W.HBox(
            [self._process_label, self._btn_run, self._btn_clear],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        history_row = W.HBox([self.history.root, self._btn_load_config])
        history_row.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Solution</div>"),
                toolbar,
                history_row,
                self._signal_picker,
                self._plot_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")
        self._update_process_label()

    def set_process(self, process: Any) -> None:
        """Set the process to run on the next Run click."""
        self.process = process
        self._update_process_label()

    def bind_to_config(self, config_widget: Any) -> None:
        """Track a ConfigurationWidget's built process automatically.

        Also remembers `config_widget` itself, so runs can be tagged with
        their source configuration's name/hash and a past run can be
        re-imported back into it (see `_on_run`/`_on_load_config`).
        """
        self._config_widget = config_widget
        config_widget.add_listener(self.set_process)
        if getattr(config_widget, "process", None) is not None:
            self.set_process(config_widget.process)

    def bind_to_data(self, data_widget: Any) -> None:
        """Overlay a DataImportWidget's loaded datasets on this widget's plot."""
        self._data_widget = data_widget
        data_widget.add_listener(self._plot_selected)

    def _display_name(self) -> str:
        """Return the label to show/record for the current process.

        Uses the bound ConfigurationWidget's own name whenever one is bound
        (never the process's internal `.name`/class name, e.g. "Batch
        Elution" -- that's an implementation detail, not what the user
        called their configuration). Falls back to the process's own name
        only when no ConfigurationWidget is bound at all, since there's
        nothing else to show in that case.
        """
        if self._config_widget is not None:
            return self._config_widget.config_name
        return getattr(self.process, "name", type(self.process).__name__)

    def _update_process_label(self) -> None:
        if self.process is None:
            self._process_label.value = "<em>No process set.</em>"
        else:
            self._process_label.value = f"<strong>Process:</strong> {self._display_name()}"

    def _tag_current_config(self) -> tuple[Optional[str], Optional[str]]:
        """Auto-save the bound ConfigurationWidget's current state, best-effort.

        Returns (config_name, config_hash) to tag a RunRecord with. Never
        raises -- a store-write failure must not block an actual simulation
        run, it just means that run's history entry has no re-importable hash.
        """
        if self._config_widget is None:
            return None, None
        try:
            self._config_widget.persist_to_store()
            return self._config_widget.config_name, self._config_widget.config_hash
        except Exception:  # noqa: BLE001
            return None, None

    def _on_run(self, _btn: Any) -> None:
        self._plot_out.clear_output()
        if self.process is None:
            self.status.value = "<span style='color:#b00020'>No process to run.</span>"
            return
        if self._config_widget is not None:
            error = self._config_widget.name_error("running a simulation")
            if error:
                self.status.value = f"<span style='color:#b00020'>{error}</span>"
                return

        label = self._display_name()
        self._btn_run.disabled = True
        self._btn_run.description = "Running..."
        self.status.value = "<span class='cadetgui-spinner'></span><em>Running simulation…</em>"
        config_name, config_hash = self._tag_current_config()
        try:
            result = self._runner(self.process)
        except Exception as exc:  # noqa: BLE001
            self.result = None
            self.history.record(
                label, error=str(exc), config_name=config_name, config_hash=config_hash
            )
            self.status.value = f"<span style='color:#b00020'>Simulation failed: {exc}</span>"
            return
        finally:
            self._btn_run.disabled = False
            self._btn_run.description = "Run simulation"

        self.history.record(label, result=result, config_name=config_name, config_hash=config_hash)
        self._load_result(result)
        self.status.value = "<em>Simulation finished.</em>"

    def _on_load_config(self, _btn: Any) -> None:
        run = self.history.selected
        if run is None or run.config_hash is None or self._config_widget is None:
            return
        self._config_widget.import_from_store(run.config_hash)

    def _on_history_pick(self, run: RunRecord) -> None:
        self._btn_load_config.layout.display = "" if run.config_hash else "none"
        self._plot_out.clear_output()
        if not run.ok:
            self.result = None
            self._signal_picker.set_options([])
            self.status.value = f"<span style='color:#b00020'>Simulation failed: {run.error}</span>"
            return
        self._load_result(run.result)
        self.status.value = f"<em>Viewing: {run.label}</em>"

    def _load_result(self, result: Any) -> None:
        self.result = result
        self._signal_picker.set_options(classify_signal_ports(result), keep_value=True)
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

            fig, ax = solution.plot()
            datasets = self._data_widget.datasets if self._data_widget else []
            for ds in datasets:
                ax.plot(ds.time_min, ds.signal, linestyle="--", label=f"{ds.label} (measured)")
            if datasets:
                ax.legend()
            display(fig)
            plt.close(fig)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
