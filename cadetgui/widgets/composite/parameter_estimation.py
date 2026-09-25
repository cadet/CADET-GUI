from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional, Sequence, Union

import ipywidgets as W
from CADETProcess.plotting import get_fig_size

from ... import configuration_store
from ...cadetprocessadapter import measurable_signal_options
from ...optimizer_runner import OptimizerRunResult, RunSpec
from ...parameter_estimation import (
    CalibrationMethod,
    EstimationResult,
    FittableParameter,
    build_estimation_problem,
    build_reference,
    calibrate_reference,
    list_fittable_parameters,
    simulate_at,
)
from ...simulation import run_process
from .._chrome import style_tag
from .._mpl_figure import display_figure, new_figure
from .._series import reference_series, solution_series
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart
from ._optimizer_runner_panel import OptimizerRunnerPanel
from .data_import import DataImportWidget
from .parameter_space import ParameterSpaceEditor

__all__ = ["ParameterEstimationWidget"]


class ParameterEstimationWidget:
    """Fit a bound configuration's column/binding parameters against experimental data.

    One configuration, one experimental dataset, one signal, SSE. This widget
    collects the inputs and hands `OptimizerRunnerPanel` (`_runner`) a `RunSpec`
    built around `cadetgui.parameter_estimation.build_estimation_problem`; the
    panel owns everything about running it (optimizer picker, Run/Cancel, live
    plot, analytics, fit table, Accept) and is shared with `CharacterizationWidget`.
    Nests `DataImportWidget` (`.data`) as its experimental-data source.

    Deliberately self-contained: its "Preview" section simulates the base
    process itself (lazily, only when the bound process changes) to show the
    reference-vs-simulated overlay, rather than reusing `SolutionWidget`'s last
    run -- the Simulation tab shows only the raw simulation, this tab owns the
    comparison view.
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
        # base process changes.
        self._display_result: Optional[Any] = None
        self._preview_process: Optional[Any] = None

        # Base-process picker, shown at the top of the run section.
        self._saved_options: list[tuple[str, Any]] = []
        self._base_process_picker = ChoiceField(
            label="Base process:", options=[(self._active_label(), None)]
        )
        self._btn_refresh_store = W.Button(description="Refresh", icon="refresh")
        self._preview_status = W.HTML("")
        self._preview_status.add_class("cadetgui-status")
        # "Experimental data" section: dataset picker + "Signal represents" row.
        self._dataset_picker = ChoiceField(label="Experimental dataset:", options=[])
        self._component_picker = ChoiceField(label="Signal represents:", options=[])
        # "Run estimation" section: which simulated port to fit against.
        self._signal_picker = ChoiceField(label="Signal:", options=[])
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
        # Result overlay: reference-vs-simulated, shown after a Preview or a finished run.
        self._plot_out = W.Image(
            format="png", layout=W.Layout(width="400px", display="none")
        )
        self._chart = ChromatogramChart(view_width=560, view_height=260, y_label="Signal")
        self._chart.layout.display = "none"
        self._chart.layout.width = "560px"

        base_process_row = W.HBox(
            [self._base_process_picker, self._btn_refresh_store],
            layout=W.Layout(flex_flow="row wrap"),
        )
        base_process_row.add_class("cadetgui-toolbar")

        self._runner = OptimizerRunnerPanel(
            build_run_spec=self._build_run_spec,
            leading=[base_process_row],
        )
        self.status = self._runner.status

        self._btn_refresh_store.on_click(lambda _btn: self._refresh_store_options())
        self._base_process_picker.observe(self._on_base_process_change, names="selected_index")
        self._signal_picker.observe(self._on_signal_change, names="selected_index")
        self._calibration_picker.observe(self._on_calibration_change, names="selected_index")
        self._dataset_picker.observe(self._on_reference_input_change, names="selected_index")
        self._component_picker.observe(self._on_reference_input_change, names="selected_index")
        for field in (self._extinction_field, self._path_length_field, self._target_area_field):
            field.observe(self._on_reference_input_change, names="value")
        self.data.add_listener(self._refresh_dataset_options)
        self._refresh_dataset_options()

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

        preview_toolbar = W.HBox(
            [self._signal_picker], layout=W.Layout(flex_flow="row wrap")
        )
        preview_toolbar.add_class("cadetgui-toolbar")
        preview_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-section-title'>Preview</div>"),
                preview_toolbar,
                self._preview_status,
                self._chart,
                self._plot_out,
            ]
        )
        preview_section.add_class("cadetgui-section")

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                W.HTML("<div class='cadetgui-panel-title'>Parameter estimation</div>"),
                data_section,
                param_space_section,
                preview_section,
                self._runner.root,
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
        self._saved_options = [(name, hash_) for name, hash_ in saved]
        self._base_process_picker.set_options(
            [(self._active_label(), None), *self._saved_options], keep_value=True
        )

    def _active_label(self) -> str:
        cw = self._config_widget
        name = (cw.config_name or "").strip() if cw is not None else ""
        return f"{name or 'Current configuration'} (Active)"

    def _refresh_active_label(self) -> None:
        label = self._active_label()
        if self._base_process_picker.option_labels[:1] == [label]:
            return
        self._base_process_picker.set_options(
            [(label, None), *self._saved_options], keep_value=True
        )

    def _on_base_process_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        hash_ = self._base_process_picker.value
        if hash_ is not None and self._config_widget is not None:
            self._config_widget.import_from_store(hash_)
        self._refresh_preview()

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

    def _refresh_preview(self, *, force: bool = False) -> None:
        """Simulate the bound process for the overlay, only if it changed since last time."""
        if self._runner._btn_run.disabled:
            return
        cw = self._config_widget
        process = cw.process if cw is not None else None
        if process is None:
            self._preview_process = None
            self._display_result = None
            self._clear_overlay()
            if cw is not None:
                self._preview_status.value = status_html("error", "No configuration to preview.")
            return
        if process is self._preview_process and not force:
            return
        self._preview_process = process
        self._preview_status.value = status_html("running", "Simulating preview…")
        try:
            self._display_result = run_process(process)
            self._redraw_overlay()
        except Exception as exc:  # noqa: BLE001
            self._display_result = None
            self._clear_overlay()
            self._preview_status.value = status_html("error", f"Preview failed: {exc}")
            return
        self._preview_status.value = ""

    def _clear_overlay(self) -> None:
        self._chart.series = []
        self._chart.layout.display = "none"
        self._plot_out.value = b""
        self._plot_out.layout.display = "none"

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
        result_solution = self._display_result.solution
        if unit not in result_solution or port not in result_solution[unit]:
            return
        solution = result_solution[unit][port]
        try:
            reference, dataset_label = self._current_reference()
        except Exception:  # noqa: BLE001
            reference, dataset_label = None, None

        series = solution_series(solution)
        if series is not None:
            if reference is not None:
                series.append(
                    reference_series(
                        f"{dataset_label} (measured)", reference.time, reference.solution[:, 0]
                    )
                )
            self._plot_out.layout.display = "none"
            self._chart.series = series
            self._chart.layout.display = ""
            return

        self._chart.layout.display = "none"
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
        self._refresh_signal_options()
        self._refresh_active_label()
        self._refresh_preview()

    def _refresh_signal_options(self) -> None:
        cw = self._config_widget
        process = cw.process if cw is not None else None
        options = measurable_signal_options(process) if process is not None else []
        if [label for label, _ in options] == self._signal_picker.option_labels:
            return
        self._signal_picker.set_options(options, keep_value=True)

    def _refresh_component_options(self) -> None:
        cw = self._config_widget
        components = cw.components if cw is not None else []
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
            return "No signal available for the current configuration."
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

    def _build_run_spec(self) -> Union[RunSpec, str]:
        showing_fit = self._last_result is not None
        self._last_result = None
        error = self._validation_error()
        if error:
            return error

        if showing_fit:
            self._preview_process = None
            self._refresh_preview()

        unit, port = self._signal_picker.value
        reference, _ = self._current_reference()
        params = list(self.param_space.params)
        selected: list[int] = []
        starts: list[float] = []
        for idx, start, lb, ub in self.param_space.rows():
            params[idx] = replace(params[idx], lb=lb, ub=ub)
            selected.append(idx)
            starts.append(start)
        process = self._config_widget.process
        column = self._config_widget._column_form.built

        try:
            problem, working_process = build_estimation_problem(
                process, column, params, selected, reference, f"{unit}.{port}",
                component_name=self._component_picker.value,
            )
        except Exception as exc:  # noqa: BLE001
            return str(exc)

        # The live preview only ever touches an independent copy of the
        # process (via `simulate_at`), never the one the worker thread is
        # actively mutating.
        def candidate_solution(x_best: Sequence[float]) -> Any:
            return simulate_at(process, column, params, selected, list(x_best)).solution[unit][port]

        def preview_series(x_best: Sequence[float]) -> Optional[list[dict[str, Any]]]:
            series = solution_series(candidate_solution(x_best))
            if series is not None and reference is not None:
                series.append(
                    reference_series("measured", reference.time, reference.solution[:, 0])
                )
            return series

        def render_preview(x_best: Sequence[float], ax: Any) -> None:
            candidate_solution(x_best).plot(ax=ax)
            if reference is not None:
                ax.plot(
                    reference.time / 60.0, reference.solution[:, 0],
                    linestyle="--", color="black", linewidth=2, label="measured",
                )
                ax.legend()

        def fitted_by_index(x_best: Any) -> dict[int, float]:
            return {idx: x_best[f"var_{idx}"] for idx in selected}

        def on_finished(result: OptimizerRunResult) -> None:
            if result.cancelled or not result.success:
                return
            self._last_result = EstimationResult(
                fitted_by_index(result.x_best), result.objective, True, result.message,
                working_process,
            )
            # Show the fitted (still detached) process's own curve until the base process changes.
            self._display_result = run_process(working_process)
            self._redraw_overlay()

        return RunSpec(
            problem, starts, render_preview,
            lambda x_best: self._fit_table_html(fitted_by_index(x_best)),
            lambda x_best: self._apply_fitted(fitted_by_index(x_best)),
            on_finished, preview_series,
        )

    def _fit_table_html(self, fitted: dict[int, float]) -> str:
        rows = "".join(
            f"<tr><td>{self.param_space.params[idx].label}</td>"
            f"<td>{self.param_space.params[idx].current_value:.4g}</td><td>{value:.4g}</td></tr>"
            for idx, value in fitted.items()
        )
        header = "<tr><th>Parameter</th><th>Before</th><th>Fitted</th></tr>"
        return f"<table>{header}{rows}</table>"

    def _apply_fitted(self, fitted: dict[int, float]) -> None:
        cw = self._config_widget
        for idx, value in fitted.items():
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

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
