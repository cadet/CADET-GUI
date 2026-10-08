from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional, Sequence, Union

import ipywidgets as W

from ...io import configuration_store
from ...optimizer_runner import OptimizerRunResult, RunSpec
from ...parameter_estimation import (
    EstimationResult,
    FittableParameter,
    build_estimation_problem,
    list_fittable_parameters,
    simulate_at,
)
from ...simulation import run_process
from .._chrome import style_tag
from .._mpl_figure import display_figure, new_figure
from .._series import reference_series, solution_series
from .._status import status_html
from ..elements import ChoiceField, ChromatogramChart
from ._optimizer_runner_panel import FIGSIZE, OptimizerRunnerPanel
from ._reference_signal import ReferenceSignalControls
from .data_import import DataImportWidget
from .parameter_space import ParameterSpaceEditor

__all__ = ["ParameterEstimationWidget"]


def _series_with_reference(solution: Any, label: str, reference: Optional[Any]) -> Optional[list]:
    series = solution_series(solution)
    if series is not None and reference is not None:
        series.append(reference_series(label, reference.time, reference.solution[:, 0]))
    return series


def _plot_reference(ax: Any, reference: Any, label: str) -> None:
    # Explicit colour: `solution.plot()`'s own cycle can hand this line the first curve's blue.
    ax.plot(
        reference.time / 60.0, reference.solution[:, 0],
        linestyle="--", color="black", linewidth=2, label=label,
    )
    ax.legend()


class ParameterEstimationWidget:
    """Fit a bound configuration's column/binding parameters against experimental data.

    One configuration, one dataset, one signal, SSE. Collects the inputs and hands
    `OptimizerRunnerPanel` a `RunSpec` built around
    `cadetgui.parameter_estimation.build_estimation_problem`; the panel owns everything
    about running it. Nests `DataImportWidget` (`.data`) as its data source.

    The "Preview" section simulates the base process itself (only when the bound process
    changes) to show the reference-vs-simulated overlay, independent of `SolutionWidget`.
    """

    def __init__(self, *, data: Optional[DataImportWidget] = None) -> None:
        self.data = data or DataImportWidget()
        self._config_widget: Optional[Any] = None
        self.param_space = ParameterSpaceEditor()
        self._last_result: Optional[EstimationResult] = None
        # The result shown in the overlay: the raw preview, or the fitted run after a fit.
        self._display_result: Optional[Any] = None
        self._preview_process: Optional[Any] = None
        # Off: configuration changes only mark the preview stale until `refresh_preview()`.
        self.auto_preview = True
        self._preview_stale = False

        self._saved_options: list[tuple[str, Any]] = []
        self._base_process_picker = ChoiceField(
            label="Base process:", options=[(self._active_label(), None)]
        )
        self._btn_refresh_store = W.Button(description="Refresh", icon="refresh")
        self._preview_status = W.HTML("")
        self._preview_status.add_class("cadetgui-status")
        self._dataset_picker = ChoiceField(label="Experimental dataset:", options=[])
        self._ref = ReferenceSignalControls(on_change=self._redraw_overlay)
        self._component_picker = self._ref.component_picker
        self._signal_picker = self._ref.signal_picker
        self._calibration_picker = self._ref.calibration_picker
        self._extinction_field = self._ref.extinction_field
        self._path_length_field = self._ref.path_length_field
        self._target_area_field = self._ref.target_area_field
        self._beer_lambert_box = self._ref.beer_lambert_box
        self._normalize_area_box = self._ref.normalize_area_box
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
        self._dataset_picker.observe(self._on_reference_input_change, names="selected_index")
        self.data.add_listener(self._refresh_dataset_options)
        self._refresh_dataset_options()

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

        self._btn_clear = W.Button(
            description="Clear", icon="eraser",
            tooltip="Remove the datasets, fit parameters and fit results from this page",
            layout=W.Layout(width="auto"),
        )
        self._btn_clear.on_click(lambda _btn: self.clear())
        header = W.HBox(
            [
                W.HTML("<div class='cadetgui-panel-title'>Parameter estimation</div>"),
                self._btn_clear,
            ],
            layout=W.Layout(justify_content="space-between", align_items="center"),
        )

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                header,
                data_section,
                param_space_section,
                preview_section,
                self._runner.root,
            ]
        )
        self.root.add_class("cadetgui-panel")

    def clear(self) -> None:
        """Remove the datasets, added parameters and fit results; ignored while a fit runs."""
        if self._runner.running:
            self.status.value = status_html("error", "Cancel the running fit before clearing.")
            return
        self.data.clear()
        self.param_space.clear()
        self._calibration_picker.selected_index = 0
        self._runner.clear()
        self._last_result = None
        self._refresh_preview(force=True)

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
        self._saved_options = list(configuration_store.list_store(store_dir=store_dir))
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

    def _on_base_process_change(self, _change: dict) -> None:
        hash_ = self._base_process_picker.value
        if hash_ is not None and self._config_widget is not None:
            self._config_widget.import_from_store(hash_)
        self._refresh_preview()

    def _on_reference_input_change(self, _change: dict) -> None:
        self._redraw_overlay()

    def _refresh_preview(self, *, force: bool = False) -> None:
        """Simulate the bound process for the overlay, only if it changed since last time."""
        if self._runner.running:
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

    def _current_reference(self) -> tuple[Optional[Any], Optional[str]]:
        """Return the calibrated reference for the picked dataset, or (None, None)."""
        dataset = self._dataset_picker.value
        if dataset is None:
            return None, None
        return self._ref.reference_for(dataset), dataset.label

    def _redraw_overlay(self) -> None:
        """Plot the shown result's signal, overlaid with the reference if a dataset is picked."""
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

        label = f"{dataset_label} (measured)"
        series = _series_with_reference(solution, label, reference)
        if series is not None:
            self._plot_out.layout.display = "none"
            self._chart.series = series
            self._chart.layout.display = ""
            return

        self._chart.layout.display = "none"
        fig = new_figure(figsize=FIGSIZE)
        ax = fig.add_subplot(111)
        solution.plot(ax=ax)
        if reference is not None:
            _plot_reference(ax, reference, label)
        display_figure(self._plot_out, fig)

    def _on_config_changed(self, _process: Any) -> None:
        cw = self._config_widget
        if cw is None or cw.column_form is None or cw.binding_form is None:
            new_params: list[FittableParameter] = []
        else:
            new_params = list_fittable_parameters(
                "column", cw.column_form.spec.fields, cw.column_form.collect_values()
            ) + list_fittable_parameters(
                "binding", cw.binding_form.spec.fields, cw.binding_form.collect_values()
            )
        self.param_space.set_params(new_params)
        self._refresh_component_options()
        self._refresh_signal_options()
        self._refresh_active_label()
        if self.auto_preview:
            self._refresh_preview()
        else:
            self._preview_stale = True
            self._preview_status.value = status_html(
                "info", "Configuration changed; the preview updates when this pane is opened."
            )

    def refresh_preview(self) -> None:
        """Simulate the preview now if the configuration changed since the last one."""
        if self._preview_stale:
            self._preview_stale = False
            self._refresh_preview()

    def _refresh_signal_options(self) -> None:
        cw = self._config_widget
        self._ref.refresh_signal_options(cw.process if cw is not None else None)

    def _refresh_component_options(self) -> None:
        cw = self._config_widget
        self._ref.refresh_component_options(cw.components if cw is not None else [])

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
        return self._ref.calibration_error()

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
        column = self._config_widget.column_form.built

        try:
            problem, working_process = build_estimation_problem(
                process, column, params, selected, reference, f"{unit}.{port}",
                component_name=self._component_picker.value,
            )
        except Exception as exc:  # noqa: BLE001
            return str(exc)

        # `simulate_at` works on a copy, never on the process the worker thread is mutating.
        def candidate_solution(x_best: Sequence[float]) -> Any:
            return simulate_at(process, column, params, selected, list(x_best)).solution[unit][port]

        def preview_series(x_best: Sequence[float]) -> Optional[list[dict[str, Any]]]:
            return _series_with_reference(candidate_solution(x_best), "measured", reference)

        def render_preview(x_best: Sequence[float], ax: Any) -> None:
            candidate_solution(x_best).plot(ax=ax)
            if reference is not None:
                _plot_reference(ax, reference, "measured")

        def fitted_by_index(x_best: Any) -> dict[int, float]:
            return {idx: x_best[f"var_{idx}"] for idx in selected}

        def on_finished(result: OptimizerRunResult) -> None:
            if result.cancelled or not result.success:
                return
            self._last_result = EstimationResult(
                fitted_by_index(result.x_best), result.objective, True, result.message,
                working_process,
            )
            # Show the fitted (still detached) process's curve until the base process changes.
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
            f"<td class='num'>{self.param_space.params[idx].current_value:.4g}</td>"
            f"<td class='num'>{value:.4g}</td></tr>"
            for idx, value in fitted.items()
        )
        header = (
            "<tr><th>Parameter</th><th class='num'>Before</th><th class='num'>Fitted</th></tr>"
        )
        return f"<table class='cadetgui-fit-table'>{header}{rows}</table>"

    def _apply_fitted(self, fitted: dict[int, float]) -> None:
        cw = self._config_widget
        for idx, value in fitted.items():
            param = self.param_space.params[idx]
            form = cw.column_form if param.owner == "column" else cw.binding_form
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
