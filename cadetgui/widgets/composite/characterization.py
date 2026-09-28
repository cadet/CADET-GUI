from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import ipywidgets as W
from CADETProcess.comparison import Comparator
from CADETProcess.comparison.difference import SSE
from CADETProcess.simulator import Cadet

from ...optimizer_runner import OptimizerRunResult, RunSpec
from ...simulation import run_process
from .._chrome import style_tag
from .._series import reference_series, solution_series
from ._characterization_stages import Stage, stage_spec
from ._optimizer_runner_panel import OptimizerRunnerPanel
from ._reference_signal import ReferenceSignalControls
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget
from .instrument import InstrumentWidget
from .parameter_history import ParameterHistoryWidget

__all__ = ["CharacterizationWidget"]


class CharacterizationWidget:
    """Fit one CADETProcess.characterization stage jointly across several experiments.

    Each stage fits a small fixed set of variables against every selected dataset at
    once: one deep-copied process and one `Comparator` per dataset, sharing one
    parameter vector. Run/cancel/live plot/Accept is `OptimizerRunnerPanel`; this
    widget builds the `RunSpec` it drives.

    `config` must be bound to `instrument` (`ConfigurationWidget(instrument=...)`) for
    the stages that write back to instrument units ("periphery", "pre_injection").
    `history`, when given, records one entry per Accept.
    """

    def __init__(
        self,
        stage: Stage,
        *,
        config: ConfigurationWidget,
        instrument: Optional[InstrumentWidget] = None,
        data: Optional[DataImportWidget] = None,
        history: Optional[ParameterHistoryWidget] = None,
        tubing_unit: Optional[str] = None,
    ) -> None:
        self._spec = stage_spec(stage, tubing_unit)
        if instrument is None and any(
            t.form == "instrument" for t in self._spec.write_targets.values()
        ):
            raise ValueError(f"stage={stage!r} writes back to the instrument -- pass instrument=")

        self.stage = stage
        self._config = config
        self._instrument = instrument
        self.data = data or DataImportWidget()
        self.history = history

        parameter_names = ", ".join(f.label or f.name for f in self._spec.fields)
        determines_header = W.HTML(
            f"<div class='cadetgui-panel-title'>{self._spec.label}</div>"
            f"<em>Determines: {parameter_names}.</em>"
        )

        # One (lb, ub) pair per variable: FormRenderer commits a single value per field.
        self._bound_fields: Dict[str, tuple[W.FloatText, W.FloatText]] = {
            f.name: (
                W.FloatText(value=f.min if f.min is not None else 0.0, description="lb:"),
                W.FloatText(value=f.max if f.max is not None else 1.0, description="ub:"),
            )
            for f in self._spec.fields
        }
        bounds_rows = [
            W.HBox([W.Label(f.label or f.name, layout=W.Layout(width="220px")), lb, ub])
            for f, (lb, ub) in zip(self._spec.fields, self._bound_fields.values())
        ]
        bounds_section = W.VBox(
            [W.HTML("<div class='cadetgui-section-title'>Search bounds</div>"), *bounds_rows]
        )
        bounds_section.add_class("cadetgui-panel")
        bounds_section.add_class("cadetgui-section")

        self._dataset_select = W.SelectMultiple(
            options=[], description="Datasets:", layout=W.Layout(width="100%", height="100px")
        )
        self._btn_refresh_datasets = W.Button(description="Refresh", icon="refresh")
        self._btn_refresh_datasets.on_click(lambda _btn: self._refresh_dataset_options())
        self.data.add_listener(self._refresh_dataset_options)

        self._ref = ReferenceSignalControls()
        self._component_picker = self._ref.component_picker
        self._signal_picker = self._ref.signal_picker
        self._calibration_picker = self._ref.calibration_picker
        self._extinction_field = self._ref.extinction_field
        self._path_length_field = self._ref.path_length_field
        self._target_area_field = self._ref.target_area_field
        self._beer_lambert_box = self._ref.beer_lambert_box
        self._normalize_area_box = self._ref.normalize_area_box

        data_section = W.VBox(
            [
                W.HTML("<div class='cadetgui-panel-title'>Experimental data</div>"),
                self.data.root,
                W.HBox(
                    [self._dataset_select, self._btn_refresh_datasets],
                    layout=W.Layout(flex_flow="row wrap"),
                ),
                W.HBox(
                    [self._component_picker, self._calibration_picker],
                    layout=W.Layout(flex_flow="row wrap"),
                ),
                self._beer_lambert_box,
                self._normalize_area_box,
            ]
        )
        data_section.add_class("cadetgui-panel")
        data_section.add_class("cadetgui-section")

        self._runner = OptimizerRunnerPanel(
            build_run_spec=self._build_run_spec, accept_label="Push to Configuration",
        )
        self.status = self._runner.status

        self.root = W.VBox(
            [
                W.HTML(style_tag()),
                determines_header,
                data_section,
                bounds_section,
                W.HBox([self._signal_picker], layout=W.Layout(flex_flow="row wrap")),
                self._runner.root,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._refresh_dataset_options()
        self._config.add_listener(self._on_config_changed)
        self._on_config_changed()

    def _refresh_dataset_options(self) -> None:
        self._dataset_select.options = [(d.label, d) for d in self.data.datasets]

    def _calibration_kwargs(self) -> Dict[str, float]:
        return self._ref.calibration_kwargs()

    def _on_config_changed(self, process: Any = None) -> None:
        process = process if process is not None else self._config.process
        self._ref.refresh_signal_options(process)
        self._ref.refresh_component_options(self._config.components)

    def _write_fitted_values(self, values: Mapping[str, float]) -> None:
        """Write `values` through the live forms so the form fields stay in sync."""
        groups = self._spec.group_by_form(values)
        for (kind, unit), updates in groups.items():
            if kind == "instrument":
                form = self._instrument._unit_forms.get(unit)
            elif kind == "column":
                form = self._config._column_form
            else:
                form = self._config._binding_form
            if form is not None:
                form.set_values({**form.collect_values(), **updates})

        # Form edits mutate the flow sheet in place without refreshing the hash or
        # notifying listeners.
        if groups:
            self._config.persistence.refresh_hash_display()
            self._config._notify()

    def _validation_error(self) -> Optional[str]:
        if self._config.process is None:
            return "No configuration to fit."
        if not self._dataset_select.value:
            return "Select at least one dataset."
        if self._signal_picker.value is None:
            return "No signal position available to compare against."
        error = self._ref.calibration_error()
        if error:
            return error
        for name, (lb, ub) in self._bound_fields.items():
            if lb.value >= ub.value:
                return f"Lower bound must be less than upper bound for {name}."
        return None

    def _build_problem(self, solution_path: str) -> tuple[Any, list[Any], list[Any]]:
        """Return the joint problem, its per-dataset processes and calibrated references."""
        component_name = self._component_picker.value
        processes, comparators, references = [], [], []
        for index, dataset in enumerate(self._dataset_select.value):
            reference = self._ref.reference_for(dataset)
            references.append(reference)
            metric = (
                SSE(reference, components=[component_name]) if component_name is not None
                else SSE(reference, use_total_concentration=True)
            )
            comparator = Comparator()
            comparator.add_difference_metric(metric, solution_path)
            comparators.append(comparator)
            # CharacterizeBase keys its callbacks by process name; deep copies share one.
            process_copy = copy.deepcopy(self._config.process)
            process_copy.name = f"{self.stage}_{dataset.label}_{index}"
            processes.append(process_copy)

        overrides = {
            name: {"lb": lb.value, "ub": ub.value} for name, (lb, ub) in self._bound_fields.items()
        }
        problem = self._spec.characterize_cls(
            self.stage, processes, comparators=comparators, simulator=Cadet(),
            **self._spec.extra_kwargs, **overrides,
        )
        # The built-in plot callback crashes `optimize(save_results=False)`.
        problem.callbacks.clear()
        return problem, processes, references

    def _build_run_spec(self) -> Union[RunSpec, str]:
        error = self._validation_error()
        if error:
            return error

        unit, port = self._signal_picker.value
        try:
            problem, processes, references = self._build_problem(f"{unit}.{port}")
        except Exception as exc:  # noqa: BLE001
            return str(exc)

        base_process = self._config.process
        first = references[0]

        def candidate_solution(x_best: Sequence[float]) -> Any:
            preview_process = copy.deepcopy(base_process)
            self._spec.apply_values(preview_process, dict(zip(self._bound_fields, x_best)))
            return run_process(preview_process).solution[unit][port]

        def preview_series(x_best: Sequence[float]) -> Optional[list[Dict[str, Any]]]:
            series = solution_series(candidate_solution(x_best))
            if series is not None:
                series.append(
                    reference_series("measured (dataset 1)", first.time, first.solution[:, 0])
                )
            return series

        def render_preview(x_best: Sequence[float], ax: Any) -> None:
            candidate_solution(x_best).plot(ax=ax)
            ax.plot(
                first.time / 60.0, first.solution[:, 0],
                linestyle="--", color="black", linewidth=2, label="measured (dataset 1)",
            )
            ax.legend()

        # Shown/pushed values are read back off the fitted process, not from the
        # optimizer's result vector, so they are what actually landed on it.
        finished: Optional[OptimizerRunResult] = None

        def render_fit_table(_x_best: Mapping[str, float]) -> str:
            confirmed = self._spec.read_values(processes[0])
            rows = "".join(
                f"<tr><td>{f.label or f.name}</td><td>{confirmed[f.name]:.4g}</td></tr>"
                for f in self._spec.fields if f.name in confirmed
            )
            return "<table><tr><th>Parameter</th><th>Fitted</th></tr>" + rows + "</table>"

        def on_finished(result: OptimizerRunResult) -> None:
            nonlocal finished
            finished = result

        def accept(_x_best: Mapping[str, float]) -> None:
            confirmed = self._spec.read_values(processes[0])
            self._write_fitted_values(confirmed)
            if self.history is not None:
                self.history.record(
                    self.stage, confirmed,
                    dataset_labels=[d.label for d in self._dataset_select.value],
                    optimizer_name=finished.optimizer_name if finished else None,
                    objective=finished.objective if finished else None,
                    config_name=self._config.config_name or None,
                    config_hash=self._config.config_hash,
                )
            self.status.value = (
                "<em>Applied fitted parameters to the configuration. "
                "Save it from the Configuration panel to persist for the next stage.</em>"
            )

        x0 = [(lb.value + ub.value) / 2.0 for lb, ub in self._bound_fields.values()]
        return RunSpec(
            problem, x0, render_preview, render_fit_table, accept, on_finished, preview_series
        )

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
