from __future__ import annotations

from typing import Any, Callable, Optional

import ipywidgets as W

from ... import configuration_store, run_store
from ...cadetprocessadapter import (
    active_inlets,
    classify_signal_ports,
    friendly_signal_options,
    measurable_signal_ports,
)
from ...simulation import run_process as _default_runner
from .._chrome import style_tag
from .._series import solution_series
from .._settings_popover import toggle_box
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart
from .run_history import RunHistoryWidget, RunRecord

__all__ = ["SolutionWidget"]


class SolutionWidget:
    """Run a CADET-Process process and plot its solution.

    Plots via `SolutionIO.plot()` directly rather than reimplementing plotting.
    """

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
        # Once the user explicitly sets the run history's own folder (via
        # "Save Options" -> "Set folder"), auto-following the bound
        # configuration's folder stops -- see `_sync_history_store_dir`.
        self._history_store_dir_overridden = False
        # Suspends `_sync_history_store_dir` while `_on_history_pick` is
        # hydrating a past run -- see that method and `set_process`.
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

        # "Save Options" groups everything about *where*/*what* gets written
        # to disk in one place: the run history's storage folder (normally
        # just following the bound configuration, see `_sync_history_store_dir`,
        # but overridable here) together with what to save on demand for the
        # currently shown result.
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
                W.HBox([self.history._store_dir_field, self.history._btn_set_store_dir]),
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
        self.history._picker.observe(self._on_history_selection_change, names="selected_index")
        self.status.add_class("cadetgui-status")

        toolbar = W.HBox(
            [self._process_label, self._btn_run, self._btn_clear],
            layout=W.Layout(flex_flow="row wrap"),
        )
        toolbar.add_class("cadetgui-toolbar")

        # `self.history._picker` directly, not `self.history.root` -- the
        # latter wraps it in its own flex-column panel, which was throwing
        # off horizontal alignment with the button sitting next to it.
        history_row = W.HBox([self.history._picker, self._btn_load_config, self._btn_delete_run])
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
        """Set the process to run on the next Run click.

        Also re-syncs the run history's storage folder, so a renamed
        configuration's saves/results always follow the current name --
        `set_process` fires on every rebuild, including a name change (see
        `ConfigurationPersistence._on_name_change` -> `ConfigurationWidget.
        _notify()`). Guarded by `_suspend_store_dir_sync`: `set_process` also
        fires mid-hydration (`_hydrate` -> `import_from_store` can rename the
        bound configuration to match a *past* run's saved state), and
        reacting there would reassign `history.store_dir` while
        `_on_history_pick` is still using `self.runs`, wiping the very
        selection being hydrated -- see
        `_hydrate_suspending_store_dir_sync`, which suspends this around
        just that call and deliberately does not catch up afterward (a
        historical run's transient rename isn't the user's own edit).
        """
        self.process = process
        self._update_process_label()
        if not self._suspend_store_dir_sync:
            self._sync_history_store_dir()

    def bind_to_config(self, config_widget: Any) -> None:
        """Track a ConfigurationWidget's built process automatically.

        Also remembers `config_widget` itself, so runs can be tagged with
        their source configuration's name/hash and a past run can be
        re-imported back into it (see `_on_run`/`_on_load_config`).

        Also always points the run history at the configuration's own
        per-configuration subfolder (see `configuration_store.config_dir`),
        so run outputs land alongside that configuration's own saved `.h5`
        with no folder to type in twice -- the configuration's folder itself
        already defaults to a real folder (`~/.cadetgui/configurations`) even
        when the user never set one explicitly, so this always resolves to
        somewhere real. Picking a different folder for the run history is
        still possible, just tucked under "Save Options" rather than offered
        as a first-class choice (see `_sync_history_store_dir`).
        """
        self._config_widget = config_widget
        config_widget.add_listener(self.set_process)
        config_widget.persistence.add_store_dir_listener(self._on_config_store_dir_change)
        self._sync_history_store_dir()
        if getattr(config_widget, "process", None) is not None:
            self.set_process(config_widget.process)

    def _on_config_store_dir_change(self, _store_dir: Any) -> None:
        self._sync_history_store_dir()

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
            self.status.value = status_html("error", f"Simulation failed: {exc}")
            return
        finally:
            self._btn_run.disabled = False
            self._btn_run.description = "Run simulation"

        self.history.record(
            label, result=result, config_name=config_name, config_hash=config_hash, run_id=run_id
        )
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
        """Run `_hydrate` with the storage-folder-follows-renames sync suspended.

        `_hydrate` -> `import_from_store` can rename the bound configuration
        to match a past run's saved state (see `set_process`'s docstring) --
        suspended so that doesn't reassign `history.store_dir`/wipe
        `self.runs` mid-hydration. Deliberately *not* re-synced afterward
        either: the run being viewed is historical, not the configuration the
        user is actively editing, so its folder shouldn't jump to match a
        transient rename that's just a side effect of viewing it -- and doing
        so would wipe the very selection `_on_history_pick` just populated.
        A genuine rename (typing in the name field) still syncs normally,
        since that goes through `set_process` outside of this suspension.
        """
        self._suspend_store_dir_sync = True
        try:
            return self._hydrate(run)
        finally:
            self._suspend_store_dir_sync = False

    def _hydrate(self, run: RunRecord) -> Any:
        """Reconstruct a persisted-but-not-yet-loaded run's result, best-effort.

        Rebuilds the run's own configuration first (`import_from_store`) so the
        `Process` handed to `load_run_results` actually matches what was run --
        not whatever the bound ConfigurationWidget currently happens to hold.
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
        # Only where something is measured -- "Save Options" below still
        # offers every port, so saved data stays complete.
        options = friendly_signal_options(
            measurable_signal_ports(
                result.process.flow_sheet.units_dict,
                classify_signal_ports(result),
                active_inlets(result.process),
            )
        )
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

    def _on_signal_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
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
        """Save the currently loaded result's plots and/or raw data, on demand.

        Scope (all signals vs. one) and which artifact types (PNG/CSV) come
        from the panel `_on_toggle_save_options` reveals -- this only ever
        acts on `self.result`, whatever's currently shown (a fresh run or a
        past one picked from history), never a whole run's worth implicitly.
        Written into a "results" subfolder of the run history's storage
        folder, kept separate from the configuration/run h5 files that live
        directly in it.
        """
        if self.result is None:
            self._save_outputs_status.value = status_html("error", "No result to save.")
            return
        if self.history.store_dir is None:
            self._save_outputs_status.value = (
                status_html("error", "No storage folder set.")
            )
            return
        save_plots = self._save_outputs_plots_checkbox.value
        save_csv = self._save_outputs_csv_checkbox.value
        if not save_plots and not save_csv:
            self._save_outputs_status.value = "<em>Nothing selected to save.</em>"
            return

        scope = self._save_outputs_scope.value
        if scope == "__all__":
            targets = [value for _label, value in classify_signal_ports(self.result)]
        elif scope is not None:
            targets = [scope]
        else:
            targets = []
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
        results_dir.mkdir(parents=True, exist_ok=True)

        import matplotlib.pyplot as plt
        import numpy as np

        saved = 0
        for unit, port in targets:
            solution = self.result.solution[unit][port]
            stem = f"{stem_prefix}_{configuration_store.safe_config_dirname(f'{unit}_{port}')}"
            if save_plots:
                fig, ax = solution.plot()
                fig.savefig(results_dir / f"{stem}.png", dpi=150, bbox_inches="tight")
                plt.close(fig)
                saved += 1
            if save_csv:
                data = np.column_stack([solution.time, solution.solution])
                header = "time," + ",".join(solution.component_system.names)
                np.savetxt(
                    results_dir / f"{stem}.csv", data, delimiter=",",
                    header=header, comments="",
                )
                saved += 1

        self._save_outputs_status.value = f"<em>Saved {saved} file(s) to {results_dir}.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
