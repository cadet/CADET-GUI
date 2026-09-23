from __future__ import annotations

from typing import Any, Callable, Optional

import ipywidgets as W

from ... import configuration_store, run_store
from ...cadetprocessadapter import classify_signal_ports
from ...simulation import run_process as _default_runner
from .._chrome import style_tag
from .._settings_popover import toggle_box
from ..elements import ChoiceField
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
        # Once the user explicitly sets the run history's own folder (via its
        # "Show details" -> "Set folder"), auto-following the bound
        # configuration's folder stops -- see `_sync_history_store_dir`.
        self._history_store_dir_overridden = False

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
        self.history = RunHistoryWidget(
            on_manual_store_dir_change=self._on_history_store_dir_manually_set
        )

        self._btn_save_outputs = W.Button(description="Save simulation outputs", icon="save")
        self._save_outputs_scope = ChoiceField(label="Signal(s):", options=[])
        self._save_outputs_plots_checkbox = W.Checkbox(
            description="Save plots (PNG)", value=True, indent=False
        )
        self._save_outputs_csv_checkbox = W.Checkbox(
            description="Save data (CSV)", value=False, indent=False
        )
        self._btn_confirm_save_outputs = W.Button(description="Save", icon="check")
        self._save_outputs_status = W.HTML()
        self._save_outputs_status.add_class("cadetgui-status")
        self._save_outputs_box = W.VBox(
            [
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
        self._btn_save_outputs.on_click(self._on_toggle_save_outputs)
        self._btn_confirm_save_outputs.on_click(self._on_confirm_save_outputs)
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
                self._btn_save_outputs,
                self._save_outputs_box,
                self._signal_picker,
                self._plot_out,
                self.status,
            ]
        )
        self.root.add_class("cadetgui-panel")
        self._update_process_label()

    def set_process(self, process: Any) -> None:
        """Set the process to run on the next Run click.

        Deliberately does *not* re-sync the run history's storage folder --
        `set_process` also fires mid-hydration (`_hydrate` -> `import_from_store`
        can rename the bound configuration to match a past run's saved state,
        which triggers this via `ConfigurationWidget._notify()`), and reacting
        there would reassign `history.store_dir` while `_on_history_pick` is
        still using `self.runs`, wiping the very selection being hydrated.
        Following a live rename isn't needed for "default to the
        configuration's folder" anyway -- `bind_to_config` and the folder's
        own change listener already cover it.
        """
        self.process = process
        self._update_process_label()

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
        still possible, just tucked under its own "Show details" rather than
        offered as a first-class choice (see `_sync_history_store_dir`).
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
        self.history.store_dir = configuration_store.config_dir(
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
            self.status.value = f"<span style='color:#b00020'>Simulation failed: {exc}</span>"
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
            self._notify()
            self.status.value = f"<span style='color:#b00020'>Simulation failed: {run.error}</span>"
            return
        if run.result is None:
            run.result = self._hydrate(run)
            if run.result is None:
                self.result = None
                self._signal_picker.set_options([])
                self._notify()
                return
        self._load_result(run.result)
        self.status.value = f"<em>Viewing: {run.label}</em>"

    def _hydrate(self, run: RunRecord) -> Any:
        """Reconstruct a persisted-but-not-yet-loaded run's result, best-effort.

        Rebuilds the run's own configuration first (`import_from_store`) so the
        `Process` handed to `load_run_results` actually matches what was run --
        not whatever the bound ConfigurationWidget currently happens to hold.
        """
        if run.run_id is None or self.history.store_dir is None:
            self.status.value = (
                "<span style='color:#b00020'>"
                "This run's result isn't available in this session."
                "</span>"
            )
            return None
        if self._config_widget is None or run.config_hash is None:
            self.status.value = (
                "<span style='color:#b00020'>"
                "No configuration bound to reload this run against."
                "</span>"
            )
            return None
        try:
            state = run_store.load_run(run.run_id, store_dir=self.history.store_dir)
            self._config_widget.import_from_store(run.config_hash)
            return run_store.load_run_results(
                state, self.process, store_dir=self.history.store_dir
            )
        except Exception as exc:  # noqa: BLE001
            self.status.value = f"<span style='color:#b00020'>Could not reload run: {exc}</span>"
            return None

    def _load_result(self, result: Any) -> None:
        self.result = result
        self._signal_picker.set_options(classify_signal_ports(result), keep_value=True)
        self._rebuild_save_outputs_scope_options()
        self._plot_selected()
        self._notify()

    def _on_clear(self, _btn: Any) -> None:
        self._plot_out.clear_output()
        self.result = None
        self._signal_picker.set_options([])
        self._rebuild_save_outputs_scope_options()
        self._notify()
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
            display(fig)
            plt.close(fig)

    def _rebuild_save_outputs_scope_options(self) -> None:
        if self.result is None:
            self._save_outputs_scope.set_options([])
            return
        options = [("All outputs", "__all__"), *classify_signal_ports(self.result)]
        self._save_outputs_scope.set_options(options, keep_value=True)

    def _on_toggle_save_outputs(self, _btn: Any) -> None:
        shown = toggle_box(self._save_outputs_box)
        self._btn_save_outputs.description = "Hide save options" if shown else "Save simulation outputs"

    def _on_confirm_save_outputs(self, _btn: Any) -> None:
        """Save the currently loaded result's plots and/or raw data, on demand.

        Scope (all signals vs. one) and which artifact types (PNG/CSV) come
        from the panel `_on_toggle_save_outputs` reveals -- this only ever
        acts on `self.result`, whatever's currently shown (a fresh run or a
        past one picked from history), never a whole run's worth implicitly.
        """
        if self.result is None:
            self._save_outputs_status.value = "<span style='color:#b00020'>No result to save.</span>"
            return
        if self.history.store_dir is None:
            self._save_outputs_status.value = (
                "<span style='color:#b00020'>No storage folder set.</span>"
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
            self._save_outputs_status.value = "<span style='color:#b00020'>No signal selected.</span>"
            return

        run = self.history.selected
        stem_prefix = (
            run.run_id
            if run is not None and run.result is self.result and run.run_id
            else run_store.new_run_id()
        )

        import matplotlib.pyplot as plt
        import numpy as np

        saved = 0
        for unit, port in targets:
            solution = self.result.solution[unit][port]
            stem = f"{stem_prefix}_{configuration_store.safe_config_dirname(f'{unit}_{port}')}"
            if save_plots:
                fig, ax = solution.plot()
                fig.savefig(self.history.store_dir / f"{stem}.png", dpi=150, bbox_inches="tight")
                plt.close(fig)
                saved += 1
            if save_csv:
                data = np.column_stack([solution.time, solution.solution])
                header = "time," + ",".join(solution.component_system.names)
                np.savetxt(
                    self.history.store_dir / f"{stem}.csv", data, delimiter=",",
                    header=header, comments="",
                )
                saved += 1

        self._save_outputs_status.value = f"<em>Saved {saved} file(s) to {self.history.store_dir}.</em>"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
