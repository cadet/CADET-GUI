from __future__ import annotations

from typing import Any, Callable, Optional

import ipywidgets as W

from ... import configuration_store, run_store
from ...cadetprocessadapter import classify_signal_ports, measurable_signal_options
from ...simulation import run_process as _default_runner
from .._chrome import style_tag
from .._series import solution_series
from .._settings_popover import toggle_box
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart
from ._result_export import save_signal_outputs
from .run_history import RunHistoryWidget, RunRecord

__all__ = ["SolutionWidget"]


class SolutionWidget:
    """Run a CADET-Process process, plot its solution and keep a history of runs."""

    def __init__(
        self,
        *,
        process: Any = None,
        runner: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._runner = runner or _default_runner
        self.process = process
        self.result: Any = None
        self._config_widget: Optional[Any] = None
        self._listeners: list[Callable[[], None]] = []
        # Setting the history folder by hand stops it following the bound configuration.
        self._history_store_dir_overridden = False
        self._suspend_store_dir_sync = False

        self._process_label = W.HTML()
        self._btn_run = W.Button(description="Run simulation", icon="play", button_style="success")
        self._btn_clear = W.Button(description="Clear", icon="trash")
        self._btn_load_config = W.Button(
            description="Load configuration", icon="upload",
            layout=W.Layout(display="none"),
        )
        self._btn_delete_run = W.Button(description="Delete run", icon="trash", disabled=True)
        self._delete_pending = False
        self._signal_picker = ChoiceField(label="Signal:", options=[])
        self._chart = ChromatogramChart(
            y_label=r"Concentration / \frac{\mathrm{mol}}{\mathrm{m}^{3}}"
        )
        self._chart.layout.display = "none"
        self._plot_out = W.Output()
        self.status = W.HTML("<em>Ready.</em>")
        self.history = RunHistoryWidget(
            on_manual_store_dir_change=self._on_history_store_dir_manually_set
        )

        self._btn_save_options = W.Button(description="Save Options", icon="chevron-down")
        self._save_outputs_scope = ChoiceField(label="Signal(s):", options=[])
        self._save_outputs_plots_checkbox = W.Checkbox(
            description="Save plots (PNG)", value=True, indent=False
        )
        self._save_outputs_csv_checkbox = W.Checkbox(
            description="Save data (CSV)", value=False, indent=False
        )
        self._btn_confirm_save_outputs = W.Button(description="Save", icon="save")
        self._save_outputs_status = W.HTML()
        self._save_outputs_status.add_class("cadetgui-status")
        self._save_options_box = W.VBox(
            [
                W.HBox([self.history.store_dir_field, self.history.set_store_dir_button]),
                W.HTML("<hr>"),
                self._save_outputs_scope,
                self._save_outputs_plots_checkbox,
                self._save_outputs_csv_checkbox,
                self._btn_confirm_save_outputs,
                self._save_outputs_status,
            ],
            layout=W.Layout(display="none"),
        )

        self._btn_run.on_click(self._on_run)
        self._btn_clear.on_click(self._on_clear)
        self._btn_load_config.on_click(self._on_load_config)
        self._btn_delete_run.on_click(self._on_delete_run)
        self._btn_save_options.on_click(self._on_toggle_save_options)
        self._btn_confirm_save_outputs.on_click(self._on_confirm_save_outputs)
        self._signal_picker.observe(self._on_signal_change, names="selected_index")
        self.history.add_listener(self._on_history_pick)
        self.history.picker.observe(self._on_history_selection_change, names="selected_index")
        self.status.add_class("cadetgui-status")

        toolbar = W.HBox(
            [self._process_label, self._btn_run, self._btn_clear],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        # The bare picker rather than `history.root`, whose panel wrapper breaks the row layout.
        history_row = W.HBox([self.history.picker, self._btn_load_config, self._btn_delete_run])
        history_row.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Solution</div>"),
                toolbar,
                history_row,
                self._signal_picker,
                self._chart,
                self._plot_out,
                self._btn_save_options,
                self._save_options_box,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")
        self._update_process_label()

    def set_process(self, process: Any) -> None:
        """Set the process to run on the next Run click and re-sync the history folder.

        The sync is skipped while a past run is being hydrated: that can rename the bound
        configuration, and following the rename would wipe the selection being hydrated.
        """
        self.process = process
        self._update_process_label()
        if not self._suspend_store_dir_sync:
            self._sync_history_store_dir()

    def bind_to_config(self, config_widget: Any) -> None:
        """Track a ConfigurationWidget's built process and point the run history at its folder.

        The widget is also kept so runs can be tagged with its name/hash and a past run
        re-imported into it.
        """
        self._config_widget = config_widget
        config_widget.add_listener(self.set_process)
        config_widget.persistence.add_store_dir_listener(
            lambda _store_dir: self._sync_history_store_dir()
        )
        self._sync_history_store_dir()
        if config_widget.process is not None:
            self.set_process(config_widget.process)

    def _refresh_workspace_header(self) -> None:
        if self._config_widget is not None:
            self._config_widget.workspace_header.refresh()

    def _sync_history_store_dir(self) -> None:
        if self._config_widget is None or self._history_store_dir_overridden:
            return
        self.history.store_dir = configuration_store.runs_dir(
            self._config_widget.config_name,
            store_dir=self._config_widget.persistence.store_dir,
        )

    def _on_history_store_dir_manually_set(self, store_dir: Any) -> None:
        self._history_store_dir_overridden = store_dir is not None
        if store_dir is None:
            self._sync_history_store_dir()

    def add_listener(self, fn: Callable[[], None]) -> None:
        """Register a callback fired (no args) whenever a new result is loaded."""
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    def _display_name(self) -> str:
        """Return the bound configuration's name, or the process's own name if none is bound."""
        if self._config_widget is not None:
            return self._config_widget.config_name
        return getattr(self.process, "name", type(self.process).__name__)

    def _update_process_label(self) -> None:
        if self.process is None:
            self._process_label.value = "<em>No process set.</em>"
        else:
            self._process_label.value = f"<strong>Process:</strong> {self._display_name()}"

    def _tag_current_config(self) -> tuple[Optional[str], Optional[str]]:
        """Save the bound configuration and return its `(name, hash)` to tag a run with.

        A store failure must not block a run; the entry then has no re-importable hash.
        """
        if self._config_widget is None:
            return None, None
        try:
            self._config_widget.persist_to_store()
            return self._config_widget.config_name, self._config_widget.config_hash
        except Exception:  # noqa: BLE001
            return None, None

    def _clear_plot(self) -> None:
        self._plot_out.clear_output()
        self._chart.series = []
        self._chart.layout.display = "none"

    def _on_run(self, _btn: Any) -> None:
        self._reset_delete_confirm()
        self._clear_plot()
        if self.process is None:
            self.status.value = status_html("error", "No process to run.")
            return
        if self._config_widget is not None:
            error = self._config_widget.name_error("running a simulation")
            if error:
                self.status.value = status_html("error", str(error))
                return

        label = self._display_name()
        self._btn_run.disabled = True
        self._btn_run.description = "Running..."
        self.status.value = status_html("running", "Running simulation…")
        config_name, config_hash = self._tag_current_config()

        run_id = None
        runner_kwargs: dict[str, Any] = {}
        if self.history.store_dir is not None:
            run_id = run_store.new_run_id()
            runner_kwargs["file_path"] = run_store.run_output_path(
                run_id, store_dir=self.history.store_dir
            )

        try:
            result = self._runner(self.process, **runner_kwargs)
        except Exception as exc:  # noqa: BLE001
            self.result = None
            self.history.record(
                label, error=str(exc), config_name=config_name, config_hash=config_hash,
                run_id=run_id,
            )
            self._refresh_workspace_header()
            self.status.value = status_html("error", f"Simulation failed: {exc}")
            return
        finally:
            self._btn_run.disabled = False
            self._btn_run.description = "Run simulation"

        self.history.record(
            label, result=result, config_name=config_name, config_hash=config_hash, run_id=run_id
        )
        self._refresh_workspace_header()
        self._load_result(result)
        self.status.value = "<em>Simulation finished.</em>"

    def _on_load_config(self, _btn: Any) -> None:
        self._reset_delete_confirm()
        run = self.history.selected
        if run is None or run.config_hash is None or self._config_widget is None:
            return
        self._config_widget.import_from_store(run.config_hash)

    def _reset_delete_confirm(self) -> None:
        self._delete_pending = False
        self._btn_delete_run.description = "Delete run"
        self._btn_delete_run.button_style = ""

    def _on_history_selection_change(self, _change: dict) -> None:
        self._reset_delete_confirm()
        selected = self.history.selected
        self._btn_delete_run.disabled = selected is None
        if selected is None:
            self._btn_load_config.layout.display = "none"

    def _on_delete_run(self, _btn: Any) -> None:
        run = self.history.selected
        if run is None:
            return
        if not self._delete_pending:
            self._delete_pending = True
            self._btn_delete_run.description = "Confirm delete?"
            self._btn_delete_run.button_style = "danger"
            return
        self._reset_delete_confirm()
        if run.run_id is not None and self.history.store_dir is not None:
            try:
                run_store.delete_run(run.run_id, store_dir=self.history.store_dir)
            except Exception as exc:  # noqa: BLE001
                self.status.value = status_html("error", f"Could not delete run: {exc}")
                return
        self.history.remove(run)
        self._refresh_workspace_header()
        self._clear_result()
        self.status.value = "<em>Ready.</em>"

    def _on_history_pick(self, run: RunRecord) -> None:
        self._btn_load_config.layout.display = "" if run.config_hash else "none"
        self._clear_plot()
        if not run.ok:
            self.result = None
            self._signal_picker.set_options([])
            self._notify()
            self.status.value = status_html("error", f"Simulation failed: {run.error}")
            return
        if run.result is None:
            run.result = self._hydrate_suspending_store_dir_sync(run)
            if run.result is None:
                self.result = None
                self._signal_picker.set_options([])
                self._notify()
                return
        self._load_result(run.result)
        self.status.value = f"<em>Viewing: {run.label}</em>"

    def _hydrate_suspending_store_dir_sync(self, run: RunRecord) -> Any:
        """Run `_hydrate` without the history folder following the rename it may cause.

        Not re-synced afterwards either: the viewed run is historical, not what the user is
        editing, and syncing would wipe the selection `_on_history_pick` just made.
        """
        self._suspend_store_dir_sync = True
        try:
            return self._hydrate(run)
        finally:
            self._suspend_store_dir_sync = False

    def _hydrate(self, run: RunRecord) -> Any:
        """Reload a persisted run's result, rebuilding its own configuration first.

        The process handed to `load_run_results` must match what was run, not whatever the
        bound configuration currently holds.
        """
        if run.run_id is None or self.history.store_dir is None:
            self.status.value = status_html(
                "error", "This run's result isn't available in this session."
            )
            return None
        if self._config_widget is None or run.config_hash is None:
            self.status.value = status_html(
                "error", "No configuration bound to reload this run against."
            )
            return None
        try:
            state = run_store.load_run(run.run_id, store_dir=self.history.store_dir)
            self._config_widget.import_from_store(run.config_hash)
            return run_store.load_run_results(
                state, self.process, store_dir=self.history.store_dir
            )
        except Exception as exc:  # noqa: BLE001
            self.status.value = status_html("error", f"Could not reload run: {exc}")
            return None

    def _load_result(self, result: Any) -> None:
        self.result = result
        # Saving still offers every port; only the plot picker is limited to measured ones.
        options = measurable_signal_options(result.process, classify_signal_ports(result))
        self._signal_picker.set_options(options, keep_value=True)
        self._rebuild_save_outputs_scope_options()
        self._plot_selected()
        self._notify()

    def _clear_result(self) -> None:
        self._clear_plot()
        self.result = None
        self._signal_picker.set_options([])
        self._rebuild_save_outputs_scope_options()
        self._notify()

    def _on_clear(self, _btn: Any) -> None:
        self._reset_delete_confirm()
        self._clear_result()
        self.status.value = "<em>Cleared.</em>"

    def _on_signal_change(self, _change: dict) -> None:
        self._plot_selected()

    def _plot_selected(self) -> None:
        if self.result is None or self._signal_picker.value is None:
            return
        unit, port = self._signal_picker.value
        solution = self.result.solution[unit][port]

        series = solution_series(solution)
        if series is not None:
            self._plot_out.clear_output()
            self._plot_out.layout.display = "none"
            self._chart.layout.display = ""
            self._chart.series = series
            return

        self._chart.series = []
        self._chart.layout.display = "none"
        self._plot_out.layout.display = ""
        self._plot_out.clear_output(wait=True)
        with self._plot_out:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, ax = solution.plot()
            display(fig)
            plt.close(fig)

    def _rebuild_save_outputs_scope_options(self) -> None:
        if self.result is None:
            self._save_outputs_scope.set_options([])
            return
        options = [("All outputs", "__all__"), *classify_signal_ports(self.result)]
        self._save_outputs_scope.set_options(options, keep_value=True)

    def _on_toggle_save_options(self, _btn: Any) -> None:
        shown = toggle_box(self._save_options_box)
        self._btn_save_options.description = "Hide Save Options" if shown else "Save Options"

    def _on_confirm_save_outputs(self, _btn: Any) -> None:
        """Save the shown result's plots and/or data under the history folder's `results/`."""
        if self.result is None:
            self._save_outputs_status.value = status_html("error", "No result to save.")
            return
        if self.history.store_dir is None:
            self._save_outputs_status.value = status_html("error", "No storage folder set.")
            return
        plots = self._save_outputs_plots_checkbox.value
        csv = self._save_outputs_csv_checkbox.value
        if not plots and not csv:
            self._save_outputs_status.value = "<em>Nothing selected to save.</em>"
            return

        scope = self._save_outputs_scope.value
        if scope == "__all__":
            targets = [value for _label, value in classify_signal_ports(self.result)]
        else:
            targets = [] if scope is None else [scope]
        if not targets:
            self._save_outputs_status.value = status_html("error", "No signal selected.")
            return

        run = self.history.selected
        stem_prefix = (
            run.run_id
            if run is not None and run.result is self.result and run.run_id
            else run_store.new_run_id()
        )
        results_dir = self.history.store_dir / "results"
        saved = save_signal_outputs(
            self.result, targets, results_dir, stem_prefix, plots=plots, csv=csv
        )
        self._save_outputs_status.value = f"<em>Saved {saved} file(s) to {results_dir}.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
