from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Optional, Sequence, Union

import ipywidgets as W
from CADETProcess.characterization import (
    CharacterizeAdsorptionParameters,
    CharacterizeBed,
    CharacterizeCapacity,
    CharacterizeParticles,
    CharacterizePreInjection,
    CharacterizeTubing,
)
from CADETProcess.comparison import Comparator
from CADETProcess.comparison.difference import SSE
from CADETProcess.simulator import Cadet

from ...cadetprocessadapter import FieldSpec, measurable_signal_options
from ...optimizer_runner import OptimizerRunResult, RunSpec
from ...parameter_estimation import (
    CalibrationMethod,
    build_reference,
    calibrate_reference,
)
from ...simulation import run_process
from .._chrome import style_tag
from .._series import reference_series, solution_series
from ..elements import ChoiceField
from ._optimizer_runner_panel import OptimizerRunnerPanel
from .configuration import ConfigurationWidget
from .data_import import DataImportWidget
from .instrument import InstrumentWidget
from .parameter_history import ParameterHistoryWidget

__all__ = ["CharacterizationWidget"]

Stage = Literal["periphery", "pre_injection", "bed", "particles", "adsorption", "capacity"]


@dataclass(frozen=True)
class _WriteTarget:
    """Where one fitted variable gets written back on Accept.

    `form` picks the target object (`instrument`'s named unit, the bound
    config's column, or its binding model); `field` is that object's real
    CADET-Process attribute name -- not necessarily the same string as the
    optimization variable's own name (e.g. `CharacterizePreInjection`'s
    `mixer_volume` variable is really the mixer's `init_liquid_volume`).
    """

    form: Literal["instrument", "column", "binding"]
    unit: Optional[str]
    field: str


@dataclass(frozen=True)
class _StageSpec:
    """One characterization stage.

    Which CADETProcess.characterization class drives it, its small fixed set
    of bound-override fields, and where each fitted value writes back to.
    """

    label: str
    characterize_cls: type
    extra_kwargs: Dict[str, Any]
    fields: tuple[FieldSpec, ...]
    write_targets: Dict[str, _WriteTarget]


def _tubing_fields(unit: str) -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            f"{unit}_length", "float", label="Length",
            min=1e-3, max=5.0, default=0.1, units=r"\mathrm{m}",
        ),
        FieldSpec(
            f"{unit}_axial_dispersion", "float", label="Axial dispersion",
            min=1e-12, max=1e-4, default=1e-7, units=r"\frac{\mathrm{m}^{2}}{\mathrm{s}}",
        ),
    )


# Static (non-`tubing_unit`-parametrized) stages. "periphery" is built
# dynamically in `__init__` instead, since its fields/write_targets depend on
# which tubing unit is passed -- see `CharacterizeTubing`'s own `tubing=`
# argument.
_STATIC_STAGE_SPECS: Dict[Stage, _StageSpec] = {
    "pre_injection": _StageSpec(
        label="System periphery (pre-injection tubing + mixer)",
        characterize_cls=CharacterizePreInjection,
        extra_kwargs={},
        fields=(
            FieldSpec(
                "tubing_pre_injection_length", "float", label="Pre-injection tubing length",
                min=1e-3, max=5.0, default=0.1, units=r"\mathrm{m}",
            ),
            FieldSpec(
                "mixer_volume", "float", label="Mixer volume",
                min=1e-9, max=1e-3, default=1e-6, units=r"\mathrm{m}^{3}",
            ),
        ),
        write_targets={
            "tubing_pre_injection_length": _WriteTarget(
                "instrument", "tubing_pre_injection", "length"
            ),
            "mixer_volume": _WriteTarget("instrument", "mixer", "init_liquid_volume"),
        },
    ),
    "bed": _StageSpec(
        label="Column bed (porosity & axial dispersion)",
        characterize_cls=CharacterizeBed,
        extra_kwargs={},
        fields=(
            FieldSpec("bed_porosity", "float", label="Bed porosity", min=0.2, max=0.8, default=0.4),
            FieldSpec(
                "axial_dispersion", "float", label="Axial dispersion",
                min=1e-12, max=1e-4, default=1e-7, units=r"\frac{\mathrm{m}^{2}}{\mathrm{s}}",
            ),
        ),
        write_targets={
            "bed_porosity": _WriteTarget("column", None, "bed_porosity"),
            "axial_dispersion": _WriteTarget("column", None, "axial_dispersion"),
        },
    ),
    "particles": _StageSpec(
        label="Particle transport (film diffusion)",
        characterize_cls=CharacterizeParticles,
        extra_kwargs={"include_film_diffusion": True},
        fields=(
            FieldSpec(
                "film_diffusion", "float", label="Film diffusion",
                min=1e-9, max=1e-3, default=1e-5, units=r"\frac{\mathrm{m}}{\mathrm{s}}",
            ),
        ),
        write_targets={"film_diffusion": _WriteTarget("column", None, "film_diffusion")},
    ),
    # Rapid-equilibrium only (`is_kinetic=False`) -- the kinetic mode adds a
    # dependent-variable pair (`adsorption_rate`/`desorption_rate` derived
    # from `equilibrium_constant`/`kinetic_constant`) that
    # `cadetgui.optimizer_runner.run_optimization` doesn't support (see its
    # own docstring note on `set_variables`); rapid equilibrium is also what
    # the reference workflow this widget targets actually uses.
    "adsorption": _StageSpec(
        label="Binding (rapid equilibrium)",
        characterize_cls=CharacterizeAdsorptionParameters,
        extra_kwargs={"is_kinetic": False},
        fields=(
            FieldSpec(
                "characteristic_charge", "float", label="Characteristic charge",
                min=0.1, max=50.0, default=5.0,
            ),
            FieldSpec(
                "adsorption_rate", "float", label="Equilibrium constant",
                min=1e-3, max=1e6, default=1.0,
            ),
        ),
        write_targets={
            "characteristic_charge": _WriteTarget("binding", None, "characteristic_charge"),
            "adsorption_rate": _WriteTarget("binding", None, "adsorption_rate"),
        },
    ),
    "capacity": _StageSpec(
        label="Binding capacity",
        characterize_cls=CharacterizeCapacity,
        extra_kwargs={},
        fields=(
            FieldSpec(
                "capacity", "float", label="Capacity",
                min=1.0, max=1000.0, default=100.0, units=r"\mathrm{mM}",
            ),
        ),
        write_targets={"capacity": _WriteTarget("binding", None, "capacity")},
    ),
}


class CharacterizationWidget:
    """Fit one CADETProcess.characterization stage jointly across several experiments.

    Deliberately NOT one of `WorkbenchWidget`'s default steps -- it overlaps
    conceptually with `ParameterEstimationWidget` (both fit column/binding
    parameters against experimental data) and is meant to be reached through
    a purpose-built notebook (`examples/characterization.ipynb`) that walks
    the staged pipeline this widget's `stage` values mirror: system
    periphery ("periphery"/"pre_injection") -> column bed ("bed") ->
    transport ("particles") -> binding ("adsorption"/"capacity").

    Unlike `ParameterEstimationWidget` (one dataset, one process, an
    arbitrary user-picked parameter set), each stage here fits a small FIXED
    set of variables (`CADETProcess.characterization.CharacterizeXxx`'s own
    `_default_variables`) jointly across every dataset the user selects --
    one deep-copied process + one `Comparator` per dataset, all sharing one
    parameter vector, which is what makes this a genuinely joint,
    multi-experiment fit rather than `ParameterEstimationWidget`'s
    single-dataset one.

    `config` must already be bound to an `InstrumentWidget` (`ConfigurationWidget
    (instrument=...)`) for `stage="periphery"`/`"pre_injection"` (writes back
    onto the instrument's own unit forms) -- pass that same `InstrumentWidget`
    as `instrument=` too, since `ConfigurationWidget` doesn't expose the one
    it's bound to. Other stages only need `config`.

    Reuses `OptimizerRunnerPanel` (cadetgui/widgets/composite/
    _optimizer_runner_panel.py) for the actual run/cancel/live-plot/accept
    chrome -- this widget only builds the `RunSpec` it drives.

    `history`, when given (a shared `ParameterHistoryWidget`, typically one
    `CharacterizationWorkbenchWidget` instance per notebook), gets one
    entry recorded on every successful Push -- which parameters, from which
    dataset(s), with what optimizer/objective, so "which experiment
    determined this value" stays answerable across the whole pipeline, not
    just this one pane. Optional: a stage pushed to without one simply
    isn't recorded anywhere beyond the live config, same as before this
    existed.
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
        if stage == "periphery":
            if tubing_unit is None:
                raise ValueError('stage="periphery" requires tubing_unit=...')
            self._spec = _StageSpec(
                label=f"System periphery ({tubing_unit})",
                characterize_cls=CharacterizeTubing,
                extra_kwargs={"tubing": tubing_unit},
                fields=_tubing_fields(tubing_unit),
                write_targets={
                    f"{tubing_unit}_length": _WriteTarget("instrument", tubing_unit, "length"),
                    f"{tubing_unit}_axial_dispersion": _WriteTarget(
                        "instrument", tubing_unit, "axial_dispersion"
                    ),
                },
            )
        else:
            if tubing_unit is not None:
                raise ValueError(f"tubing_unit only applies to stage='periphery', got {stage!r}")
            self._spec = _STATIC_STAGE_SPECS[stage]

        write_forms = {t.form for t in self._spec.write_targets.values()}
        if "instrument" in write_forms and instrument is None:
            raise ValueError(f"stage={stage!r} writes back to the instrument -- pass instrument=")

        self.stage = stage
        self._config = config
        self._instrument = instrument
        self.data = data or DataImportWidget()
        # Optional -- a stage pushed to without a shared history simply
        # isn't recorded anywhere beyond the live config, same as before
        # this existed.
        self.history = history

        # What this stage actually determines, up front and at a glance --
        # separate from the bound-override editor below (secondary/optional:
        # most of the time the default bounds are fine), so "which
        # parameters does this pane push to the configuration" is answered
        # in one line without reading the whole form.
        parameter_names = ", ".join(f.label or f.name for f in self._spec.fields)
        determines_header = W.HTML(
            f"<div class='cadetgui-panel-title'>{self._spec.label}</div>"
            f"<em>Determines: {parameter_names}.</em>"
        )

        # One (lb, ub) FloatText pair per stage variable -- a bound-override
        # editor, not a single-value form (FormRenderer/ModelSpec commit one
        # value per field, the wrong shape for this).
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

        self._component_picker = ChoiceField(label="Signal represents:", options=[])
        self._signal_picker = ChoiceField(label="Signal:", options=[])

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
            [self._extinction_field, self._path_length_field], layout=W.Layout(display="none")
        )
        self._normalize_area_box = W.HBox(
            [self._target_area_field], layout=W.Layout(display="none")
        )
        self._calibration_picker.observe(self._on_calibration_change, names="selected_index")

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
                W.HBox(
                    [self._signal_picker], layout=W.Layout(flex_flow="row wrap")
                ),
                self._runner.root,
            ]
        )
        self.root.add_class("cadetgui-panel")

        self._refresh_dataset_options()
        self._config.add_listener(self._refresh_signal_options)
        self._refresh_signal_options()

    def _refresh_dataset_options(self) -> None:
        self._dataset_select.options = [(d.label, d) for d in self.data.datasets]

    def _on_calibration_change(self, change: dict) -> None:
        if change.get("name") != "selected_index":
            return
        method = self._calibration_picker.value
        self._beer_lambert_box.layout.display = "" if method == "beer_lambert" else "none"
        self._normalize_area_box.layout.display = "" if method == "normalize_area" else "none"

    def _calibration_kwargs(self) -> Dict[str, float]:
        method = self._calibration_picker.value
        if method == "beer_lambert":
            return {
                "extinction_coefficient": self._extinction_field.value,
                "path_length": self._path_length_field.value,
            }
        if method == "normalize_area":
            return {"target_area": self._target_area_field.value}
        return {}

    def _refresh_signal_options(self, process: Any = None) -> None:
        process = process if process is not None else self._config.process
        options = measurable_signal_options(process) if process is not None else []
        if [label for label, _ in options] == self._signal_picker.option_labels:
            return
        self._signal_picker.set_options(options, keep_value=True)

    def _apply_values_to_process(self, process: Any, values: Mapping[str, float]) -> None:
        """Write `{variable_name: value}` onto `process`'s real attributes.

        Uses `self._spec.write_targets` -- the same mapping `_on_accept`
        writes into the live `instrument`/`config` forms with -- so a preview
        candidate is simulated with exactly the parameters a real Accept
        would apply.
        """
        flow_sheet = process.flow_sheet
        for name, value in values.items():
            target = self._spec.write_targets.get(name)
            if target is None:
                continue
            if target.form == "instrument":
                unit = flow_sheet[target.unit]
            elif target.form == "column":
                unit = flow_sheet.column
            else:
                unit = flow_sheet.column.binding_model
            current = getattr(unit, target.field)
            wrapped = type(current)([value]) if isinstance(current, (list, tuple)) else value
            setattr(unit, target.field, wrapped)

    def _read_fitted_values(self, process: Any) -> Dict[str, float]:
        """Read the fitted values back off `process`'s real attributes.

        Inverse of `_apply_values_to_process`, via the same `write_targets`
        mapping. Used instead of trusting `OptimizerRunResult.x_best`
        directly once a run finishes: the lonza_poc reference project's own
        ARCHITECTURE.md documents this exact failure mode under "Ordering"
        -- a sibling module there read fitted values straight from the
        optimizer's result vector rather than off the process, and "the
        store receives whatever the optimizer's vector holds, in whatever
        space and order the problem happens to use, with no point at which
        the process itself confirms the value landed where the path says."
        By the time this is called, `run_optimization` has already called
        `problem.set_variables(results.x[0])` on `process` (one of the
        deep-copied per-dataset processes `_build_run_spec` built the
        problem from), so reading it back here is a real confirmation, not
        a formality.
        """
        flow_sheet = process.flow_sheet
        values: Dict[str, float] = {}
        for name, target in self._spec.write_targets.items():
            if target.form == "instrument":
                unit = flow_sheet[target.unit]
            elif target.form == "column":
                unit = flow_sheet.column
            else:
                unit = flow_sheet.column.binding_model
            current = getattr(unit, target.field)
            values[name] = current[0] if isinstance(current, (list, tuple)) else current
        return values

    def _write_fitted_values(self, x_best: Mapping[str, float]) -> None:
        """Write `x_best` back through the live forms, not by mutating `.process` directly.

        A direct attribute write (as `_apply_values_to_process` does for a
        throwaway preview copy) would desync the visible form fields from the
        real process -- the next unrelated edit to that form would then
        silently overwrite the accepted fit with the form's own (stale)
        collected values. Going through `FormRenderer.set_values()` keeps
        both in sync, matching `ParameterEstimationWidget._on_accept`'s same
        rule for column/binding.
        """
        instrument_updates: Dict[str, Dict[str, float]] = {}
        column_updates: Dict[str, float] = {}
        binding_updates: Dict[str, float] = {}
        for name, value in x_best.items():
            target = self._spec.write_targets.get(name)
            if target is None:
                continue
            if target.form == "instrument":
                instrument_updates.setdefault(target.unit, {})[target.field] = value
            elif target.form == "column":
                column_updates[target.field] = value
            else:
                binding_updates[target.field] = value

        for unit_name, updates in instrument_updates.items():
            form = self._instrument._unit_forms.get(unit_name) if self._instrument else None
            if form is not None:
                form.set_values({**form.collect_values(), **updates})

        if column_updates and self._config._column_form is not None:
            form = self._config._column_form
            form.set_values({**form.collect_values(), **column_updates})
        if binding_updates and self._config._binding_form is not None:
            form = self._config._binding_form
            form.set_values({**form.collect_values(), **binding_updates})

        # Editing a column/binding/instrument-unit form directly (rather than
        # through the model form's own rebuild) mutates the live flow sheet
        # in place but doesn't itself refresh the hash display or notify
        # `ConfigurationWidget`'s own listeners (e.g. a bound SolutionWidget)
        # -- there's no public "I changed the process externally" hook, so
        # this reaches for the same private refresh `_on_process_built` uses.
        if instrument_updates or column_updates or binding_updates:
            self._config.persistence.refresh_hash_display()
            self._config._notify()

    def _validation_error(self) -> Optional[str]:
        if self._config.process is None:
            return "No configuration to fit."
        if not self._dataset_select.value:
            return "Select at least one dataset."
        if self._signal_picker.value is None:
            return "No signal position available to compare against."
        method: CalibrationMethod = self._calibration_picker.value
        if method == "beer_lambert" and (
            self._extinction_field.value <= 0 or self._path_length_field.value <= 0
        ):
            return "Enter a positive extinction coefficient and path length."
        if method == "normalize_area" and self._target_area_field.value == 0:
            return "Enter a nonzero injected amount to normalize against."
        for name, (lb, ub) in self._bound_fields.items():
            if lb.value >= ub.value:
                return f"Lower bound must be less than upper bound for {name}."
        return None

    def _build_run_spec(self) -> Union[RunSpec, str]:
        error = self._validation_error()
        if error:
            return error

        base_process = self._config.process
        unit, port = self._signal_picker.value
        solution_path = f"{unit}.{port}"
        component_name = self._component_picker.value

        processes = []
        comparators = []
        references = []
        for dataset in self._dataset_select.value:
            reference = build_reference(
                dataset.label, dataset.time_min, dataset.signal, component_name=component_name
            )
            reference = calibrate_reference(
                reference, self._calibration_picker.value, **self._calibration_kwargs(),
            )
            references.append(reference)
            metric = (
                SSE(reference, components=[component_name]) if component_name is not None
                else SSE(reference, use_total_concentration=True)
            )
            comparator = Comparator()
            comparator.add_difference_metric(metric, solution_path)
            comparators.append(comparator)
            # `CharacterizeBase.__init__` keys its internal callback lookup
            # by `process.name` -- `copy.deepcopy` preserves the original
            # name on every copy, so without renaming, a second (or later)
            # dataset's comparator would silently collide with and shadow
            # the first's in that lookup (known upstream sharp edge, per
            # lonza_poc's own STATUS.md: "objective-name collisions in
            # multi-process fits").
            process_copy = copy.deepcopy(base_process)
            process_copy.name = f"{self.stage}_{dataset.label}_{len(processes)}"
            processes.append(process_copy)

        overrides = {
            name: {"lb": lb.value, "ub": ub.value} for name, (lb, ub) in self._bound_fields.items()
        }
        try:
            problem = self._spec.characterize_cls(
                self.stage, processes,
                comparators=comparators, simulator=Cadet(),
                **self._spec.extra_kwargs, **overrides,
            )
        except Exception as exc:  # noqa: BLE001
            return str(exc)

        # `CharacterizeBase.__init__` auto-registers its own plot callback
        # (saves a comparison PNG per evaluated individual). `run_optimization`
        # always calls `optimize(..., save_results=False)`, which leaves
        # `OptimizerBase.callbacks_dir` at `None` -- fine for a problem with
        # no callbacks (every hand-built `run_estimation` problem), but
        # `run_final_processing` unconditionally does `self.callbacks_dir /
        # sub_dir` whenever `n_callbacks > 0`, crashing with `TypeError:
        # unsupported operand type(s) for /: 'NoneType' and 'str'` for any
        # CharacterizeXxx problem (confirmed live). This widget already
        # renders its own live/final comparison via `render_preview` below,
        # so CharacterizeBase's own callback is both redundant and this
        # module's only path that ever hits the crash -- drop it rather than
        # work around `optimize()`'s `save_results` handling.
        problem.callbacks.clear()

        x0 = [(lb.value + ub.value) / 2.0 for lb, ub in self._bound_fields.values()]

        def candidate_solution(x_best: Sequence[float]) -> Any:
            values = dict(zip(self._bound_fields, x_best))
            preview_process = copy.deepcopy(base_process)
            self._apply_values_to_process(preview_process, values)
            return run_process(preview_process).solution[unit][port]

        def preview_series(x_best: Sequence[float]) -> Optional[list[Dict[str, Any]]]:
            series = solution_series(candidate_solution(x_best))
            if series is not None:
                series.append(
                    reference_series(
                        "measured (dataset 1)", references[0].time, references[0].solution[:, 0]
                    )
                )
            return series

        def render_preview(x_best: Sequence[float], ax: Any) -> None:
            candidate_solution(x_best).plot(ax=ax)
            ax.plot(
                references[0].time / 60.0, references[0].solution[:, 0],
                linestyle="--", color="black", linewidth=2, label="measured (dataset 1)",
            )
            ax.legend()

        # `x_best`, as handed to `render_fit_table`/`accept` below, is
        # `OptimizerRunResult.x_best` -- built from the optimizer's own
        # result vector, not read off the process. Read the confirmed
        # landed values back off `processes[0]` instead (see
        # `_read_fitted_values`'s own docstring for why this isn't a
        # formality) and use those everywhere a fitted value is shown,
        # pushed, or recorded, ignoring `x_best`'s own content.
        last_result: Dict[str, Any] = {}

        def render_fit_table(_x_best: Mapping[str, float]) -> str:
            confirmed = self._read_fitted_values(processes[0])
            rows = "".join(
                f"<tr><td>{f.label or f.name}</td><td>{confirmed[f.name]:.4g}</td></tr>"
                for f in self._spec.fields if f.name in confirmed
            )
            return "<table><tr><th>Parameter</th><th>Fitted</th></tr>" + rows + "</table>"

        def on_finished(result: OptimizerRunResult) -> None:
            last_result["optimizer_name"] = result.optimizer_name
            last_result["objective"] = result.objective

        def accept(_x_best: Mapping[str, float]) -> None:
            confirmed = self._read_fitted_values(processes[0])
            self._write_fitted_values(confirmed)
            if self.history is not None:
                self.history.record(
                    self.stage, confirmed,
                    dataset_labels=[d.label for d in self._dataset_select.value],
                    optimizer_name=last_result.get("optimizer_name"),
                    objective=last_result.get("objective"),
                    config_name=self._config.config_name or None,
                    config_hash=self._config.config_hash,
                )
            self.status.value = (
                "<em>Applied fitted parameters to the configuration. "
                "Save it from the Configuration panel to persist for the next stage.</em>"
            )

        return RunSpec(
            problem, x0, render_preview, render_fit_table, accept, on_finished, preview_series
        )

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
