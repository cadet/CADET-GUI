from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional, Union

import ipywidgets as W
import numpy as np
from CADETProcess.plotting import get_fig_size

from ...optimizer_runner import (
    OPTIMIZERS,
    OptimizerRunResult,
    RunSpec,
    run_optimization,
)
from .._mpl_figure import display_figure, new_figure
from ..elements import ChoiceField

__all__ = ["OptimizerRunnerPanel"]


class OptimizerRunnerPanel:
    """Optimizer-picker/Run/Cancel/Accept/live-progress chrome, generic over what's optimized.

    Originally the run-section of `ParameterEstimationWidget` (single-process,
    SSE-only fits); extracted so `CharacterizationWidget`
    (`widgets/composite/characterization.py`) can drive the exact same
    threading/cancel/live-plot/accept mechanics against a
    `CADETProcess.characterization.CharacterizeXxx`-built `OptimizationProblem`
    instead, without duplicating any of it.

    `build_run_spec` is called fresh on every "Run" click and must return a
    `cadetgui.optimizer_runner.RunSpec`, or a validation-error string (shown
    in `.status`, run aborted). Everything problem-specific -- how to preview
    a candidate point, how to render the fit table, where fitted values get
    written back -- lives on that `RunSpec`, not here.
    """

    # Matches CADET-Process's own "1_col" default, same choice
    # `ParameterEstimationWidget` made for its own plots.
    _FIGSIZE = get_fig_size("1_col")

    def __init__(self, *, build_run_spec: Callable[[], Union[RunSpec, str]]) -> None:
        self._build_run_spec = build_run_spec
        self._run_done = threading.Event()
        self._cancel_event = threading.Event()
        self._progress: dict[str, Any] = {"optimizer": None, "result": None}
        self._last_run_spec: Optional[RunSpec] = None
        self._last_result: Optional[OptimizerRunResult] = None

        self._optimizer_picker = ChoiceField(
            label="Optimizer:", options=[(name, name) for name in OPTIMIZERS]
        )
        # One knob box per OPTIMIZERS entry, built generically from its
        # `knobs` tuple -- adding another optimizer to the registry needs no
        # change here. Only the selected optimizer's box is visible at a time.
        self._knob_fields: dict[str, list[W.IntText]] = {
            name: [W.IntText(value=knob.default, description=knob.label) for knob in spec.knobs]
            for name, spec in OPTIMIZERS.items()
        }
        self._knob_boxes: dict[str, W.HBox] = {
            name: W.HBox(fields, layout=W.Layout(display="none", flex_flow="row wrap"))
            for name, fields in self._knob_fields.items()
        }
        self._knob_boxes[self._optimizer_picker.value].layout.display = ""

        self._btn_run = W.Button(description="Run", icon="magic", button_style="success")
        self._btn_cancel = W.Button(
            description="Cancel", icon="stop", button_style="danger",
            layout=W.Layout(display="none"),
        )
        self._btn_accept = W.Button(
            description="Accept fitted parameters", icon="check",
            layout=W.Layout(display="none"),
        )
        self._live_plot_checkbox = W.Checkbox(description="Live plot", value=False, indent=False)
        self._elapsed_label = W.HTML(value="")

        # `W.Image`, not `W.Output` -- see `_mpl_figure.display_figure`'s
        # docstring for why (background-thread rendering, confirmed live).
        self._live_plot_out = W.Image(
            format="png", layout=W.Layout(width="700px", display="none")
        )
        self._live_plot_error = W.HTML(value="")
        self._fit_table = W.HTML()
        self._analytics_error = W.HTML(value="")
        self._convergence_out = W.Image(
            format="png", layout=W.Layout(width="400px", display="none")
        )
        self._pairwise_out = W.Image(
            format="png", layout=W.Layout(width="500px", display="none")
        )
        self.status = W.HTML("<em>Ready.</em>")
        self.status.add_class("cadetgui-status")

        self._btn_run.on_click(self._on_run)
        self._btn_cancel.on_click(self._on_cancel)
        self._btn_accept.on_click(self._on_accept)
        self._optimizer_picker.observe(self._on_optimizer_change, names="selected_index")

        optimizer_row = W.HBox(
            [self._optimizer_picker, *self._knob_boxes.values()],
            layout=W.Layout(flex_flow="row wrap"),
        )
        optimizer_row.add_class("cadetgui-toolbar")

        self.root = W.VBox(
            [
                optimizer_row,
                W.HBox([self._btn_run, self._btn_cancel, self._btn_accept, self._elapsed_label]),
                self._live_plot_checkbox,
                self._live_plot_error,
                self._live_plot_out,
                self._fit_table,
                W.HTML("<div class='cadetgui-panel-title'>Convergence &amp; correlation</div>"),
                self._analytics_error,
                self._convergence_out,
                self._pairwise_out,
                self.status,
            ]
        )

    def _on_optimizer_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        selected = self._optimizer_picker.value
        for name, box in self._knob_boxes.items():
            box.layout.display = "" if name == selected else "none"

    def _on_run(self, _btn: Any) -> None:
        for img in (self._live_plot_out, self._convergence_out, self._pairwise_out):
            img.value = b""
            img.layout.display = "none"
        self._live_plot_error.value = ""
        self._analytics_error.value = ""
        self._fit_table.value = ""
        self._btn_accept.layout.display = "none"
        self._last_result = None
        self._elapsed_label.value = ""

        run_spec = self._build_run_spec()
        if isinstance(run_spec, str):
            self.status.value = f"<span style='color:#b00020'>{run_spec}</span>"
            return
        self._last_run_spec = run_spec

        optimizer_name = self._optimizer_picker.value
        optimizer_kwargs = {
            knob.attr: field.value
            for knob, field in zip(
                OPTIMIZERS[optimizer_name].knobs, self._knob_fields[optimizer_name]
            )
        }

        self._btn_run.disabled = True
        self._btn_run.description = "Running..."
        self._btn_cancel.layout.display = ""
        self.status.value = "<span class='cadetgui-spinner'></span><em>Running…</em>"

        self._run_done.clear()
        self._cancel_event.clear()
        self._progress = {"optimizer": None, "result": None}
        start_time = time.monotonic()

        # Worker runs the fit on a background thread -- otherwise nothing
        # (elapsed timer, live plot) could update at all until it finished.
        # The ticker only ever touches the caller's own preview mechanism
        # via `render_preview`, which must itself never mutate anything the
        # worker thread is concurrently writing to (a fresh deep-copied
        # process per preview, same discipline `simulate_at` already uses).
        worker = threading.Thread(
            target=self._run_worker, args=(run_spec, optimizer_name, optimizer_kwargs), daemon=True
        )
        ticker = threading.Thread(
            target=self._tick_progress, args=(start_time, run_spec), daemon=True
        )
        worker.start()
        ticker.start()

    def _run_worker(
        self, run_spec: RunSpec, optimizer_name: str, optimizer_kwargs: dict[str, int]
    ) -> None:
        result = run_optimization(
            run_spec.problem, optimizer_name, optimizer_kwargs, run_spec.x0,
            cancel_event=self._cancel_event,
            on_optimizer_ready=lambda opt: self._progress.update(optimizer=opt),
        )
        self._progress["result"] = result
        self._run_done.set()

    def _tick_progress(self, start_time: float, run_spec: RunSpec) -> None:
        last_n_gen = 0
        while not self._run_done.wait(timeout=0.5):
            last_n_gen = self._progress_tick(start_time, run_spec, last_n_gen)

        # Runs once the worker has set `_run_done` -- the one point the
        # ticker and the (already-finished) worker are guaranteed not to be
        # touching Output widgets at the same time.
        self._finish_run(self._progress["result"], start_time, run_spec)

    def _progress_tick(self, start_time: float, run_spec: RunSpec, last_n_gen: int) -> int:
        """One tick's worth of progress reporting. Returns the new `last_n_gen`.

        Split out from `_tick_progress`'s loop so it's callable directly in
        tests, without any real waiting/threading involved.
        """
        elapsed = time.monotonic() - start_time
        self._elapsed_label.value = f"<em>{elapsed:.0f}s elapsed</em>"

        optimizer = self._progress.get("optimizer")
        if not self._live_plot_checkbox.value or optimizer is None:
            return last_n_gen
        n_gen = len(optimizer.results.populations)
        if n_gen == 0 or n_gen == last_n_gen:
            return last_n_gen
        self._redraw_live_plot(optimizer, run_spec)
        return n_gen

    def _redraw_live_plot(self, optimizer: Any, run_spec: RunSpec) -> None:
        # A failure here must never be silent -- shown in the panel itself
        # rather than leaving it blank for an entire run with zero indication
        # why.
        try:
            results = optimizer.results
            x_best = list(results.x[0])
            f_history = np.asarray(results.f_best_history).reshape(-1)

            width, height = self._FIGSIZE
            fig = new_figure(figsize=(2 * width, height))  # two "1_col" panels side by side
            ax1 = fig.add_subplot(1, 2, 1)
            ax2 = fig.add_subplot(1, 2, 2)

            run_spec.render_preview(x_best, ax1)
            ax1.set_title("Current best")

            ax2.plot(f_history)
            ax2.set_xlabel("Generation")
            ax2.set_ylabel("Objective")
            ax2.set_title("Objective history")

            fig.tight_layout()
            display_figure(self._live_plot_out, fig)
            self._live_plot_error.value = ""
        except Exception as exc:  # noqa: BLE001 -- best-effort per tick, but visibly
            self._live_plot_error.value = (
                f"<span style='color:#b00020'>Live plot error: {exc}</span>"
            )

    def _on_cancel(self, _btn: Any) -> None:
        self._cancel_event.set()
        self._btn_cancel.disabled = True
        optimizer_name = self._optimizer_picker.value
        if OPTIMIZERS[optimizer_name].is_population_based:
            # Population-based optimizers evaluate their whole population
            # before the per-generation cancel check is next reached -- set
            # the right expectation instead of looking stuck.
            self._btn_cancel.description = "Cancelling… (finishing generation)"
        else:
            self._btn_cancel.description = "Cancelling…"

    def _finish_run(self, result: OptimizerRunResult, start_time: float, run_spec: RunSpec) -> None:
        self._btn_run.disabled = False
        self._btn_run.description = "Run"
        self._btn_cancel.layout.display = "none"
        self._btn_cancel.disabled = False
        self._btn_cancel.description = "Cancel"
        self._elapsed_label.value = ""
        elapsed = time.monotonic() - start_time

        optimizer = self._progress.get("optimizer")
        if optimizer is not None:
            self._render_analytics(optimizer)

        if result.cancelled:
            self.status.value = f"<em>{result.message} ({elapsed:.0f}s)</em>"
        elif not result.success:
            self.status.value = f"<span style='color:#b00020'>{result.message}</span>"
        else:
            self._last_result = result
            self.status.value = (
                f"<em>{result.message} Objective: {result.objective:.4g}. ({elapsed:.0f}s)</em>"
            )
            self._fit_table.value = run_spec.render_fit_table(result.x_best)
            self._btn_accept.layout.display = ""

        if run_spec.on_finished is not None:
            run_spec.on_finished(result)

    def _render_analytics(self, optimizer: Any) -> None:
        """Show CADET-Process's own post-run analytics from `optimizer.results`.

        Not something computed here -- `OptimizationResults.plot_convergence`/
        `.plot_pairwise` (correlation/confidence/uncertainty output exists
        nowhere else in CADET-Process's optimization module). Best-effort: a
        failure here must be visible, not swallowed.
        """
        try:
            results = optimizer.results
            if len(results.populations) == 0:
                return  # nothing ran yet (e.g. cancelled before generation 1)

            fig1 = new_figure(figsize=self._FIGSIZE)
            ax1 = fig1.subplots(nrows=1, ncols=1, squeeze=False).reshape(-1)
            results.plot_convergence(ax=ax1)
            display_figure(self._convergence_out, fig1)

            # Mirrors CADET-Process's own `results.plot_figures()` guard --
            # a single variable's pairwise grid is a degenerate 1x1 plot.
            n_var = len(results.x[0])
            if n_var > 1:
                width, _ = self._FIGSIZE
                fig2 = new_figure(figsize=(width * n_var * 0.8, width * n_var * 0.8))
                ax2 = fig2.subplots(nrows=n_var, ncols=n_var, squeeze=False)
                results.plot_pairwise(ax=ax2)
                display_figure(self._pairwise_out, fig2)
            self._analytics_error.value = ""
        except Exception as exc:  # noqa: BLE001 -- best-effort, but visibly
            self._analytics_error.value = (
                f"<span style='color:#b00020'>Analytics error: {exc}</span>"
            )

    def _on_accept(self, _btn: Any) -> None:
        if self._last_result is None or self._last_run_spec is None:
            return
        self._last_run_spec.accept(self._last_result.x_best)
        self._btn_accept.layout.display = "none"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
