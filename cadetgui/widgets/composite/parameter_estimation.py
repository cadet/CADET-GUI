from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any, Optional

import ipywidgets as W
import numpy as np
from CADETProcess.plotting import get_fig_size

from ... import configuration_store
from ...cadetprocessadapter import classify_signal_ports
from ...parameter_estimation import (
    OPTIMIZERS,
    CalibrationMethod,
    EstimationResult,
    FittableParameter,
    build_reference,
    calibrate_reference,
    list_fittable_parameters,
    run_estimation,
    simulate_at,
)
from ...simulation import run_process
from .._chrome import style_tag
from .._mpl_figure import display_figure, new_figure
from ..elements import ChoiceField
from .data_import import DataImportWidget
from .parameter_space import ParameterSpaceEditor

__all__ = ["ParameterEstimationWidget"]


class ParameterEstimationWidget:
    """Fit a bound configuration's column/binding parameters against experimental data.

    A deliberately narrow first slice of PRODUCT_VISION.md §16: one configuration,
    one experimental dataset, one signal, SSE, Nelder-Mead. See
    `cadetgui.parameter_estimation.run_estimation` for the actual fitting logic --
    this widget only collects inputs and renders results. Nests `DataImportWidget`
    (`.data`) as its experimental-data source.

    Deliberately self-contained: it runs its own preview simulation (via
    "Preview") to discover signal options and show the reference-vs-simulated
    overlay, rather than reusing `SolutionWidget`'s last run -- the Simulation
    tab shows only the raw simulation, this tab owns the comparison view.
    """

    def __init__(self, *, data: Optional[DataImportWidget] = None) -> None:
        self.data = data or DataImportWidget()
        self._config_widget: Optional[Any] = None
        # Owns the "Add parameter" picker + rows (each with its own start/lb/ub
        # fields); its own row state survives a config edit or a row being
        # removed and re-added -- see ParameterSpaceEditor.set_params.
        self.param_space = ParameterSpaceEditor()
        self._last_result: Optional[EstimationResult] = None
        # The SimulationResults currently shown in the overlay -- the raw
        # preview until a fit succeeds, then the fitted run, until the next
        # "Preview" resets it.
        self._display_result: Optional[Any] = None
        # Live-progress state for a running fit -- see `_on_run`/`_tick_progress`.
        self._run_done = threading.Event()
        self._progress: dict[str, Any] = {"optimizer": None}
        # Set by "Cancel" -- checked once per generation inside run_estimation
        # (`cancel_event`), the only point that actually stops a running
        # optimizer for any of them (Nelder-Mead, U-NSGA-III, ...): see
        # `cadetgui.parameter_estimation._install_cancel_hook` for why raising
        # from an evaluator or an `add_callback` doesn't work.
        self._cancel_event = threading.Event()

        # "Run estimation" section: base-process picker + Preview button.
        self._base_process_picker = ChoiceField(
            label="Base process:", options=[("Current configuration", None)]
        )
        self._btn_refresh_store = W.Button(description="Refresh", icon="refresh")
        self._btn_preview = W.Button(description="Preview", icon="eye")
        # "Experimental data" section: dataset picker + "Signal represents" row.
        self._dataset_picker = ChoiceField(label="Experimental dataset:", options=[])
        self._component_picker = ChoiceField(label="Signal represents:", options=[])
        # "Run estimation" section: which simulated port to fit against.
        self._signal_picker = ChoiceField(label="Signal:", options=[])
        self._optimizer_picker = ChoiceField(
            label="Optimizer:", options=[(name, name) for name in OPTIMIZERS]
        )
        # One knob box per OPTIMIZERS entry, built generically from its
        # `knobs` tuple -- adding another optimizer to the registry needs no
        # change here, its fields just show up automatically. Only the
        # selected optimizer's box is visible at a time (`_on_optimizer_change`),
        # same show/hide pattern as the calibration-method fields below.
        # Matches CADET-Process's own NelderMead default (`maxiter=1000`,
        # `scipyAdapter.py`) -- 50 was too low even for a single fitted
        # parameter, let alone several; `0` for a U-NSGA-III knob means "let
        # CADET-Process size it automatically" (see `OPTIMIZERS`'s docstring).
        self._knob_fields: dict[str, list[W.IntText]] = {
            name: [W.IntText(value=knob.default, description=knob.label) for knob in spec.knobs]
            for name, spec in OPTIMIZERS.items()
        }
        self._knob_boxes: dict[str, W.HBox] = {
            name: W.HBox(fields, layout=W.Layout(display="none", flex_flow="row wrap"))
            for name, fields in self._knob_fields.items()
        }
        # "Experimental data" section: calibration method + its own fields
        # (only one of the two boxes below is shown at a time).
        self._calibration_picker = ChoiceField(
            label="Calibration:",
            options=[
                ("None (raw signal)", "none"),
                ("Beer-Lambert (absorbance → concentration)", "beer_lambert"),
                ("Normalize by injected amount", "normalize_area"),
            ],
        )
        self._extinction_field = W.FloatText(value=1.0, description="Extinction coeff.:")
        self._path_length_field = W.FloatText(value=1.0, description="Path length (cm):")
        self._target_area_field = W.FloatText(value=1.0, description="Injected amount:")
        self._beer_lambert_box = W.HBox(
            [self._extinction_field, self._path_length_field],
            layout=W.Layout(display="none"),
        )
        self._normalize_area_box = W.HBox(
            [self._target_area_field], layout=W.Layout(display="none")
        )
        # Run/Cancel/Accept button row + the elapsed-time label next to it.
        self._btn_run = W.Button(description="Run estimation", icon="magic", button_style="success")
        self._btn_cancel = W.Button(
            description="Cancel", icon="stop", button_style="danger",
            layout=W.Layout(display="none"),
        )
        self._btn_accept = W.Button(
            description="Accept fitted parameters", icon="check",
            layout=W.Layout(display="none"),
        )
        self._live_plot_checkbox = W.Checkbox(
            description="Live plot", value=False, indent=False
        )
        self._elapsed_label = W.HTML(value="")
        # Live-fit panel: current-best-vs-reference + objective-history plot,
        # redrawn every tick while "Live plot" is checked (see _redraw_live_plot).
        # `W.Image` (a plain `.value` trait holding PNG bytes), not `W.Output`
        # -- `Output`'s capture-based `display()` doesn't reliably route from
        # a background thread in a real Jupyter kernel (confirmed: elapsed
        # label/status/fit table, all direct trait assignments, updated fine
        # from the ticker thread; every `Output`-based plot render silently
        # never appeared). A direct trait assignment is the same proven
        # mechanism as those, so it works from any thread the same way.
        # `display="none"` until there's an actual image -- an empty/unset
        # `Image.value` otherwise renders as the browser's broken-image icon.
        # A fixed CSS `width` (not `max_width`/percentage, and not left
        # unset) is what actually bounds the display size correctly both
        # ways: unset let the (higher-dpi, "1_col"-sized) native pixel size
        # overflow past a narrower panel; `max_width="100%"` on its own
        # previously stretched a *smaller* (100dpi) source up to fill a
        # *wider* container and went blurry. A fixed width does neither --
        # same displayed size regardless of native pixels or container width.
        self._live_plot_out = W.Image(
            format="png", layout=W.Layout(width="700px", display="none")
        )
        self._live_plot_error = W.HTML(value="")
        # Result table (parameter/before/fitted) + the reference-vs-simulated
        # overlay plot, both shown after a Preview or a finished run.
        self._fit_table = W.HTML()
        self._plot_out = W.Image(
            format="png", layout=W.Layout(width="400px", display="none")
        )
        # Post-run analytics, from CADET-Process's own OptimizationResults --
        # not something we compute ourselves. `plot_convergence` (best/avg
        # objective vs. evaluations) always makes sense; `plot_pairwise`
        # (histograms + scatter of the fitted variables across the final
        # population) only if more than one parameter was fitted, same guard
        # CADET-Process's own `results.plot_figures()` uses.
        self._analytics_error = W.HTML(value="")
        self._convergence_out = W.Image(
            format="png", layout=W.Layout(width="400px", display="none")
        )
        self._pairwise_out = W.Image(
            format="png", layout=W.Layout(width="500px", display="none")
        )
        # Status line at the bottom of the "Run estimation" section.
        self.status = W.HTML("<em>Ready.</em>")
        self.status.add_class("cadetgui-status")

        self._btn_run.on_click(self._on_run)
        self._btn_cancel.on_click(self._on_cancel)
        self._btn_accept.on_click(self._on_accept)
        self._btn_refresh_store.on_click(lambda _btn: self._refresh_store_options())
        self._btn_preview.on_click(self._on_preview)
        self._base_process_picker.observe(self._on_base_process_change, names="selected_index")
        self._signal_picker.observe(self._on_signal_change, names="selected_index")
        self._optimizer_picker.observe(self._on_optimizer_change, names="selected_index")
        self._calibration_picker.observe(self._on_calibration_change, names="selected_index")
        self._dataset_picker.observe(self._on_reference_input_change, names="selected_index")
        self._component_picker.observe(self._on_reference_input_change, names="selected_index")
        for field in (self._extinction_field, self._path_length_field, self._target_area_field):
            field.observe(self._on_reference_input_change, names="value")
        self.data.add_listener(self._refresh_dataset_options)
        self._refresh_dataset_options()

        base_process_row = W.HBox(
            [self._base_process_picker, self._btn_refresh_store, self._btn_preview],
            layout=W.Layout(flex_flow="row wrap"),
        )
        base_process_row.add_class("cadetgui-toolbar")

        # "Signal represents" and calibration are both about *interpreting
        # the imported measurement* -- they belong with the data import, not
        # mixed in among run controls (maxiter, live plot, ...).
        dataset_row = W.HBox(
            [self._dataset_picker, self._component_picker],
            layout=W.Layout(flex_flow="row wrap"),
        )
        dataset_row.add_class("cadetgui-toolbar")

        calibration_row = W.HBox(
            [self._calibration_picker, self._beer_lambert_box, self._normalize_area_box],
            layout=W.Layout(flex_flow="row wrap"),
        )
        calibration_row.add_class("cadetgui-toolbar")

        data_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-panel-title'>Experimental data</div>"),
                self.data.root,
                dataset_row,
                calibration_row,
            ]
        )
        data_section.add_class("cadetgui-panel")
        data_section.add_class("cadetgui-section")

        param_space_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-panel-title'>Configure parameter space</div>"),
                self.param_space.root,
            ]
        )
        param_space_section.add_class("cadetgui-panel")
        param_space_section.add_class("cadetgui-section")

        # Default-selected optimizer's knob box starts visible; the rest stay
        # hidden until picked -- same as the calibration-method fields.
        self._knob_boxes[self._optimizer_picker.value].layout.display = ""

        run_toolbar = W.HBox(
            [self._signal_picker, self._live_plot_checkbox],
            layout=W.Layout(flex_flow="row wrap"),
        )
        run_toolbar.add_class("cadetgui-toolbar")

        optimizer_row = W.HBox(
            [self._optimizer_picker, *self._knob_boxes.values()],
            layout=W.Layout(flex_flow="row wrap"),
        )
        optimizer_row.add_class("cadetgui-toolbar")

        run_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-panel-title'>Run estimation</div>"),
                base_process_row,
                run_toolbar,
                optimizer_row,
                W.HBox([self._btn_run, self._btn_cancel, self._btn_accept, self._elapsed_label]),
                self._live_plot_error,
                self._live_plot_out,
                self._fit_table,
                self._plot_out,
                W.HTML("<div class='cadetgui-panel-title'>Convergence &amp; correlation</div>"),
                self._analytics_error,
                self._convergence_out,
                self._pairwise_out,
                self.status,
            ]
        )
        run_section.add_class("cadetgui-panel")
        run_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Parameter estimation</div>"),
                data_section,
                param_space_section,
                run_section,
            ]
        )
        self.root.add_class("cadetgui-panel")

    def bind_to_config(self, config_widget: Any) -> None:
        """Track a ConfigurationWidget's column/binding parameters to fit."""
        self._config_widget = config_widget
        config_widget.add_listener(self._on_config_changed)
        self._on_config_changed(config_widget.process)
        self._refresh_store_options()

    def _refresh_dataset_options(self) -> None:
        self._dataset_picker.set_options([(d.label, d) for d in self.data.datasets])

    def _refresh_store_options(self) -> None:
        store_dir = self._config_widget.persistence.store_dir if self._config_widget else None
        saved = configuration_store.list_store(store_dir=store_dir)
        options = [("Current configuration", None)] + [(name, hash_) for name, hash_ in saved]
        self._base_process_picker.set_options(options, keep_value=True)

    def _on_base_process_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        hash_ = self._base_process_picker.value
        if hash_ is not None and self._config_widget is not None:
            self._config_widget.import_from_store(hash_)
        self._on_preview(None)

    def _on_optimizer_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        selected = self._optimizer_picker.value
        for name, box in self._knob_boxes.items():
            box.layout.display = "" if name == selected else "none"

    def _on_calibration_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        method = self._calibration_picker.value
        self._beer_lambert_box.layout.display = "" if method == "beer_lambert" else "none"
        self._normalize_area_box.layout.display = "" if method == "normalize_area" else "none"
        self._redraw_overlay()

    def _on_reference_input_change(self, _change: dict) -> None:
        self._redraw_overlay()

    def _calibration_kwargs(self) -> dict[str, float]:
        method = self._calibration_picker.value
        if method == "beer_lambert":
            return {
                "extinction_coefficient": self._extinction_field.value,
                "path_length": self._path_length_field.value,
            }
        if method == "normalize_area":
            return {"target_area": self._target_area_field.value}
        return {}

    def _on_preview(self, _btn: Any) -> None:
        """Simulate the current base process once: discover signal ports and overlay it."""
        if self._config_widget is None or self._config_widget.process is None:
            self.status.value = "<span style='color:#b00020'>No configuration to preview.</span>"
            return
        self.status.value = "<span class='cadetgui-spinner'></span><em>Simulating preview…</em>"
        self._display_result = run_process(self._config_widget.process)
        options = classify_signal_ports(self._display_result)
        self._signal_picker.set_options(options, keep_value=True)
        self._redraw_overlay()
        self.status.value = "<em>Preview ready.</em>"

    def _on_signal_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        self._redraw_overlay()

    def _current_reference(self) -> tuple[Optional[Any], Optional[str]]:
        """Return the calibrated reference for the picked dataset, or (None, None)."""
        dataset = self._dataset_picker.value
        if dataset is None:
            return None, None
        reference = build_reference(
            dataset.label, dataset.time_min, dataset.signal,
            component_name=self._component_picker.value,
        )
        reference = calibrate_reference(
            reference, self._calibration_picker.value, **self._calibration_kwargs()
        )
        return reference, dataset.label

    # Matches CADET-Process's own "1_col" default (`CADETProcess.plotting.
    # figure_layouts`) -- `solution.plot()` used this by default before this
    # widget started always passing its own `ax` (required for thread safety,
    # see `_mpl_figure.new_figure`); without picking it explicitly here too,
    # the figure silently grew to matplotlib's much larger default size instead.
    _FIGSIZE = get_fig_size("1_col")

    def _redraw_overlay(self) -> None:
        """Plot the current display result's signal, overlaid with the reference if picked."""
        if self._display_result is None or self._signal_picker.value is None:
            return
        unit, port = self._signal_picker.value
        solution = self._display_result.solution[unit][port]
        try:
            reference, dataset_label = self._current_reference()
        except Exception:  # noqa: BLE001
            reference, dataset_label = None, None

        fig = new_figure(figsize=self._FIGSIZE)
        ax = fig.add_subplot(111)
        solution.plot(ax=ax)
        if reference is not None:
            label = f"{dataset_label} (measured)"
            t_min = reference.time / 60.0
            # Explicit high-contrast color -- solution.plot()'s own component
            # colors come from a separate cycle that can otherwise hand this
            # line the same blue as the first (e.g. salt/non-binding) curve.
            ax.plot(
                t_min, reference.solution[:, 0],
                linestyle="--", color="black", linewidth=2, label=label,
            )
            ax.legend()
        display_figure(self._plot_out, fig)

    def _on_config_changed(self, _process: Any) -> None:
        cw = self._config_widget
        if cw is None or cw._column_form is None or cw._binding_form is None:
            new_params: list[FittableParameter] = []
        else:
            new_params = list_fittable_parameters(
                "column", cw._column_form.spec.fields, cw._column_form.collect_values()
            ) + list_fittable_parameters(
                "binding", cw._binding_form.spec.fields, cw._binding_form.collect_values()
            )
        self.param_space.set_params(new_params)
        self._refresh_component_options()

    def _refresh_component_options(self) -> None:
        cw = self._config_widget
        components = list(cw._components.value) if cw is not None else []
        options = [(name, name) for name in components]
        options.append(("Total (sum of all components)", None))
        # Skip re-selecting when the component list is unchanged -- both "Total"
        # and "nothing selected yet" have value None, so a blind set_options()
        # here would silently bounce a deliberate "Total" pick back to index 0
        # on every unrelated field edit (which also fires this refresh).
        if [label for label, _ in options] == self._component_picker.option_labels:
            return
        self._component_picker.set_options(options, keep_value=True)

    def _validation_error(self) -> Optional[str]:
        if self._config_widget is None or self._config_widget.process is None:
            return "No configuration to fit."
        if self._dataset_picker.value is None:
            return "Import or select an experimental dataset first."
        if self._signal_picker.value is None:
            return "Preview the process to see available signals first."
        if not self.param_space:
            return "Add at least one parameter to fit."
        for idx, start, lb, ub in self.param_space.rows():
            if not (lb <= start <= ub):
                label = self.param_space.params[idx].label
                return (
                    f"Start value for {label} ({start:.4g}) must be "
                    f"within its bounds [{lb:.4g}, {ub:.4g}]."
                )
        method: CalibrationMethod = self._calibration_picker.value
        if method == "beer_lambert" and (
            self._extinction_field.value <= 0 or self._path_length_field.value <= 0
        ):
            return "Enter a positive extinction coefficient and path length."
        if method == "normalize_area" and self._target_area_field.value == 0:
            return "Enter a nonzero injected amount to normalize against."
        return None

    def _on_run(self, _btn: Any) -> None:
        for img in (self._plot_out, self._live_plot_out, self._convergence_out, self._pairwise_out):
            img.value = b""
            img.layout.display = "none"
        self._live_plot_error.value = ""
        self._analytics_error.value = ""
        self._btn_accept.layout.display = "none"
        self._last_result = None
        self._elapsed_label.value = ""
        error = self._validation_error()
        if error:
            self.status.value = f"<span style='color:#b00020'>{error}</span>"
            return

        unit, port = self._signal_picker.value
        reference, _ = self._current_reference()
        params = list(self.param_space.params)
        selected = []
        starts = []
        for idx, start, lb, ub in self.param_space.rows():
            params[idx] = replace(params[idx], lb=lb, ub=ub)
            selected.append(idx)
            starts.append(start)
        process = self._config_widget.process
        column = self._config_widget._column_form.built

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
        self.status.value = "<span class='cadetgui-spinner'></span><em>Fitting…</em>"

        self._run_done.clear()
        self._cancel_event.clear()
        self._progress = {"optimizer": None, "result": None}
        start_time = time.monotonic()

        # Run the (potentially long) fit on a background thread -- otherwise
        # nothing (elapsed timer, live plot, the UI in general) could update
        # at all until it finished, since Python/Jupyter is single-threaded
        # for anything running inline in a button click handler. The ticker
        # only ever touches an *independent* copy of the process (via
        # `simulate_at`), never the one the worker thread is actively
        # mutating. Worker starts first: it's what eventually sets
        # `_run_done`, which the ticker's own loop is waiting on.
        worker = threading.Thread(
            target=self._run_estimation_worker,
            args=(
                process, column, params, selected, reference, unit, port, starts,
                optimizer_name, optimizer_kwargs,
            ),
            daemon=True,
        )
        ticker = threading.Thread(
            target=self._tick_progress,
            args=(start_time, process, column, params, selected, reference, unit, port),
            daemon=True,
        )
        worker.start()
        ticker.start()

    def _run_estimation_worker(
        self, process: Any, column: Any, params: list[FittableParameter],
        selected: list[int], reference: Any, unit: str, port: str,
        starts: list[float], optimizer_name: str, optimizer_kwargs: dict[str, int],
    ) -> None:
        try:
            result = run_estimation(
                process, column, params, selected, reference, f"{unit}.{port}",
                optimizer_name=optimizer_name, optimizer_kwargs=optimizer_kwargs,
                starts=starts, component_name=self._component_picker.value,
                on_optimizer_ready=lambda opt: self._progress.update(optimizer=opt),
                cancel_event=self._cancel_event,
            )
        except Exception as exc:  # noqa: BLE001 -- run_estimation already catches its own
            result = EstimationResult({}, None, False, str(exc))
        self._progress["result"] = result
        self._run_done.set()

    def _tick_progress(
        self, start_time: float, process: Any, column: Any,
        params: list[FittableParameter], selected: list[int],
        reference: Any, unit: str, port: str,
    ) -> None:
        last_n_gen = 0
        while not self._run_done.wait(timeout=0.5):
            last_n_gen = self._progress_tick(
                start_time, process, column, params, selected,
                reference, unit, port, last_n_gen,
            )

        # Runs once the worker has set `_run_done` -- the one point the
        # ticker and the (already-finished) worker are guaranteed not to be
        # touching Output widgets at the same time.
        self._finish_run(self._progress["result"], start_time)

    def _progress_tick(
        self, start_time: float, process: Any, column: Any,
        params: list[FittableParameter], selected: list[int],
        reference: Any, unit: str, port: str, last_n_gen: int,
    ) -> int:
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
        self._redraw_live_plot(optimizer, process, column, params, selected, reference, unit, port)
        return n_gen

    def _redraw_live_plot(
        self, optimizer: Any, process: Any, column: Any,
        params: list[FittableParameter], selected: list[int],
        reference: Any, unit: str, port: str,
    ) -> None:
        # A failure here must never be silent -- it previously was
        # (bare `except: return`), which meant a real bug could make the
        # live panel stay empty for an entire run with zero indication why.
        # Show the actual error in the panel itself instead of guessing.
        try:
            results = optimizer.results
            x_best = list(results.x[0])
            f_history = np.asarray(results.f_best_history).reshape(-1)
            preview = simulate_at(process, column, params, selected, x_best)

            solution = preview.solution[unit][port]
            width, height = self._FIGSIZE
            fig = new_figure(figsize=(2 * width, height))  # two "1_col" panels side by side
            ax1 = fig.add_subplot(1, 2, 1)
            ax2 = fig.add_subplot(1, 2, 2)
            solution.plot(ax=ax1)
            if reference is not None:
                ax1.plot(
                    reference.time / 60.0, reference.solution[:, 0],
                    linestyle="--", color="black", linewidth=2, label="measured",
                )
                ax1.legend()
            ax1.set_title("Current best vs. reference")

            ax2.plot(f_history)
            ax2.set_xlabel("Generation")
            ax2.set_ylabel("Objective (SSE)")
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
            # before the per-generation cancel check is next reached (see
            # `_install_cancel_hook`'s docstring) -- set the right
            # expectation instead of looking stuck.
            self._btn_cancel.description = "Cancelling… (finishing generation)"
        else:
            self._btn_cancel.description = "Cancelling…"

    def _finish_run(self, result: EstimationResult, start_time: float) -> None:
        self._btn_run.disabled = False
        self._btn_run.description = "Run estimation"
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
            return
        if not result.success:
            self.status.value = f"<span style='color:#b00020'>{result.message}</span>"
            return

        self._last_result = result
        self.status.value = (
            f"<em>{result.message} Objective (SSE): {result.objective:.4g}. "
            f"({elapsed:.0f}s)</em>"
        )
        self._render_fit_table(result)
        # Show the fitted (still detached) process's own curve from here on, until
        # the next "Preview" resets the overlay back to the unfitted baseline.
        self._display_result = run_process(result.fitted_process)
        self._redraw_overlay()
        self._btn_accept.layout.display = ""

    def _render_analytics(self, optimizer: Any) -> None:
        """Show CADET-Process's own post-run analytics from `optimizer.results`.

        Not something computed here -- `OptimizationResults.plot_convergence`/
        `.plot_pairwise` (confirmed, not assumed: neither correlation,
        confidence, nor uncertainty output exists anywhere else in
        CADET-Process's optimization module, so these two are genuinely what
        there is to surface). Best-effort: a failure here must be visible,
        not swallowed -- same rule as `_redraw_live_plot`'s fix earlier.
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

    def _render_fit_table(self, result: EstimationResult) -> None:
        rows = "".join(
            f"<tr><td>{self.param_space.params[idx].label}</td>"
            f"<td>{self.param_space.params[idx].current_value:.4g}</td><td>{value:.4g}</td></tr>"
            for idx, value in result.fitted.items()
        )
        self._fit_table.value = (
            "<table><tr><th>Parameter</th><th>Before</th><th>Fitted</th></tr>" + rows + "</table>"
        )

    def _on_accept(self, _btn: Any) -> None:
        if self._last_result is None:
            return
        cw = self._config_widget
        for idx, value in self._last_result.fitted.items():
            param = self.param_space.params[idx]
            form = cw._column_form if param.owner == "column" else cw._binding_form
            element = form.element(param.name)
            if param.component_index is None:
                element.value = value
            else:
                values = list(element.value)
                values[param.component_index] = value
                element.value = values
        self.status.value = "<em>Applied fitted parameters to the configuration.</em>"
        self._btn_accept.layout.display = "none"

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
