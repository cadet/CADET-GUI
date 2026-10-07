"""One measured run paired with the process recipe that should reproduce it.

A `Comparison` holds the recipe, the measured channel, the observation point,
the clock alignment, the per-trace baseline/normalization and the metric. It
builds a fresh process from the recipe plus a `ParameterStore`, an aligned
`ReferenceIO`, and a CADET-Process `Comparator`. Headless (no ipywidgets).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
from CADETProcess import calibration
from CADETProcess.characterization import setup_comparators
from CADETProcess.comparison import Comparator, difference
from CADETProcess.processModel import ComponentSystem, Process
from CADETProcess.reference import ReferenceIO
from CADETProcess.solution import slice_solution

from . import process_builder
from .cadetprocessadapter import process_phase_spans, sample_injection_times
from .configuration_store import ConfigurationState, InstrumentState
from .experimental_data import ExperimentalRun, read_experimental_csv, to_time
from .parameter_store import ParameterStore, apply_store
from .simulation import run_process

__all__ = ["Comparison", "ComparisonPreview", "recipe_from_dict"]

_NORMALIZATION_KINDS = ("none", "area")


def recipe_from_dict(raw: Mapping[str, Any]) -> ConfigurationState:
    """Rebuild a `ConfigurationState` from its `dataclasses.asdict` form."""
    raw = dict(raw)
    instrument = raw.pop("instrument", None)
    return ConfigurationState(
        **raw, instrument=InstrumentState(**instrument) if instrument else None
    )


BASELINE_NOT_FOUND = "No flat baseline found in the measured trace."


@dataclass(frozen=True)
class ComparisonPreview:
    """One simulation at a given store, set against the aligned reference."""

    name: str
    simulated_time: np.ndarray
    simulated_values: np.ndarray
    reference_time: np.ndarray
    reference_values: np.ndarray
    metric: str
    value: float


@dataclass
class Comparison:
    """One measured run + recipe + channel + observation point + alignment + metric.

    `run` is the loaded `ExperimentalRun`; it is attached at runtime and never
    serialized. `baseline_window` and `measured_injection` are in the run's own
    x unit (mL or s); `window` is in seconds on the simulated clock.
    `experiment_type` is an id from `characterization_guide.EXPERIMENT_TYPES`, or `None`.
    """

    name: str
    data_file: str
    channel: str
    recipe: ConfigurationState
    solution_path: str
    flow_rate: Optional[float] = None
    overrides: dict = field(default_factory=dict)
    injection_marker: Optional[str] = None
    measured_injection: Optional[float] = None
    baseline_window: Optional[tuple] = None
    normalization: dict = field(default_factory=lambda: {"kind": "none"})
    components: Optional[list] = None
    metric: str = "NRMSE"
    window: tuple = (None, None)
    probe: Optional[str] = None
    experiment_type: Optional[str] = None
    run: Optional[ExperimentalRun] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON form (everything but `run`)."""
        return {
            "name": self.name,
            "data_file": self.data_file,
            "channel": self.channel,
            "flow_rate": self.flow_rate,
            "recipe": asdict(self.recipe),
            "overrides": dict(self.overrides),
            "injection_marker": self.injection_marker,
            "measured_injection": self.measured_injection,
            "baseline_window": (
                list(self.baseline_window) if self.baseline_window is not None else None
            ),
            "normalization": dict(self.normalization),
            "solution_path": self.solution_path,
            "components": list(self.components) if self.components is not None else None,
            "metric": self.metric,
            "window": list(self.window),
            "probe": self.probe,
            "experiment_type": self.experiment_type,
        }

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], base_dir: "Path | str | None" = None
    ) -> "Comparison":
        """Rebuild from `to_dict`'s form; with `base_dir`, also load `data_file` into `run`."""
        raw = dict(raw)
        raw["recipe"] = recipe_from_dict(raw["recipe"])
        if raw.get("baseline_window") is not None:
            raw["baseline_window"] = tuple(raw["baseline_window"])
        raw["window"] = tuple(raw.get("window") or (None, None))
        comparison = cls(**raw)
        if base_dir is not None:
            content = (Path(base_dir) / comparison.data_file).read_bytes()
            comparison.run = read_experimental_csv(content, comparison.name)
        return comparison

    @property
    def resolved_flow_rate(self) -> Optional[float]:
        """`flow_rate`, else the recipe's `flow_rate` model value (overrides first)."""
        if self.flow_rate is not None:
            return float(self.flow_rate)
        value = {**self.recipe.model_values, **self.overrides}.get("flow_rate")
        return float(value) if value is not None else None

    def build_process(self, store: ParameterStore) -> Process:
        """Build the recipe's process, named after this comparison, with `store` applied."""
        process = process_builder.build_process(self.recipe, overrides=self.overrides)
        process.name = self.name
        apply_store(process, store)
        return process

    def _to_seconds(self, x: float) -> float:
        if self.run.x_basis == "time":
            return float(x)
        flow_rate = self.resolved_flow_rate
        if flow_rate is None:
            raise ValueError(
                f"Comparison {self.name!r}: a flow rate is required to convert the "
                "run's volume axis to time."
            )
        return float(x) * 1e-6 / flow_rate

    def measured_injection_x(self) -> Optional[float]:
        """Return the injection position in run x units: marker, else `measured_injection`."""
        if self.injection_marker is None:
            return self.measured_injection
        for x, text in self.run.markers:
            if text.startswith(self.injection_marker):
                return x
        raise ValueError(
            f"Comparison {self.name!r}: no marker starting with "
            f"{self.injection_marker!r}. Available markers: "
            f"{[text for _, text in self.run.markers]}"
        )

    @staticmethod
    def simulated_injection_time(process: Process) -> float:
        """First sample-loop injection, else the start of the first phase, else 0."""
        injections = sample_injection_times(process)
        if injections:
            return injections[0]
        spans = process_phase_spans(process)
        return spans[0]["start"] if spans else 0.0

    def build_reference(self, process: Process) -> ReferenceIO:
        """Return the measured channel on `process`'s clock, baseline-corrected and scaled.

        Without a marker or `measured_injection`, the run's clock is taken as the
        simulated one.
        """
        if self.run is None:
            raise ValueError(f"Comparison {self.name!r}: no experimental run loaded.")
        if self.channel not in self.run.channels:
            raise ValueError(
                f"Comparison {self.name!r}: unknown channel {self.channel!r}. "
                f"Available: {list(self.run.channels)}"
            )
        flow_rate = self.resolved_flow_rate
        time, values = to_time(self.run, self.channel, flow_rate)
        order = np.argsort(time)
        reference = ReferenceIO(self.name, time[order], values[order], flow_rate=flow_rate)

        baseline = {}
        if self.baseline_window is not None:
            start, end = self.baseline_window
            baseline = {
                "start": self._to_seconds(start) if start is not None else None,
                "end": self._to_seconds(end) if end is not None else None,
            }

        kind = self.normalization.get("kind", "none")
        if kind not in ("area", "none"):
            raise ValueError(f"Comparison {self.name!r}: unknown normalization {kind!r}.")
        try:
            if kind == "area":
                reference = calibration.correct_baseline_and_normalize(
                    reference,
                    float(self.normalization["target_area"]),
                    start_baseline=baseline.get("start"),
                    end_baseline=baseline.get("end"),
                )
            elif baseline:
                reference = calibration.correct_baseline(
                    reference, baseline["start"], baseline["end"]
                )
        except ValueError as exc:
            if "baseline points" not in str(exc):
                raise
            raise ValueError(
                f"{BASELINE_NOT_FOUND} The baseline is taken from the points closest to the "
                "trace's minimum, so a single dip or a drifting signal hides the flat part."
            ) from exc

        injection_x = self.measured_injection_x()
        shift = 0.0
        if injection_x is not None:
            shift = self.simulated_injection_time(process) - self._to_seconds(injection_x)
        time = reference.time + shift
        valid = (time >= 0) & (time <= process.cycle_time)

        names = self.components if self.components and len(self.components) == 1 else None
        return ReferenceIO(
            self.name,
            time[valid],
            reference.solution[valid],
            flow_rate=flow_rate,
            component_system=ComponentSystem(list(names)) if names else None,
        )

    def build(self, store: ParameterStore) -> tuple[Process, Comparator]:
        """Return this comparison's process (with `store` applied) and its comparator."""
        process = self.build_process(store)
        reference = self.build_reference(process)
        single = self.components is not None and len(self.components) == 1
        start, end = self.window
        (comparator,) = setup_comparators(
            process,
            reference,
            solution_path=self.solution_path,
            metrics=[self.metric],
            components=list(self.components) if single else None,
            start=start,
            end=end,
        )
        if not single:
            for metric in comparator.metrics:
                _sum_components(metric, self.components)
        return process, comparator

    def evaluate(self, store: ParameterStore) -> ComparisonPreview:
        """Simulate once at `store` and return the simulated and reference traces and metric."""
        process, comparator = self.build(store)
        results = run_process(process)
        (metric,) = comparator.metrics
        simulated = slice_solution(
            comparator.extract_solution(results, metric),
            metric.components,
            metric.use_total_concentration,
            metric.use_total_concentration_components,
        )
        reference = metric.reference_original
        return ComparisonPreview(
            name=self.name,
            simulated_time=np.asarray(simulated.time),
            simulated_values=np.asarray(simulated.solution)[:, 0],
            reference_time=np.asarray(reference.time),
            reference_values=np.asarray(reference.solution)[:, 0],
            metric=self.metric,
            value=float(comparator.evaluate(results)[0]),
        )

    def problems(self) -> list[str]:
        """Return reasons this comparison cannot be built or run; empty if none found."""
        found = []
        if self.run is None:
            found.append(f"No data loaded for {self.data_file!r}.")
        else:
            if self.channel not in self.run.channels:
                found.append(
                    f"Unknown channel {self.channel!r}; available: {list(self.run.channels)}."
                )
            if self.injection_marker is not None and not any(
                text.startswith(self.injection_marker) for _, text in self.run.markers
            ):
                found.append(f"No run-log marker starts with {self.injection_marker!r}.")
            if self.run.x_basis == "volume" and self.resolved_flow_rate is None:
                found.append("A flow rate is required for a volume-axis run.")

        kind = self.normalization.get("kind", "none")
        if kind not in _NORMALIZATION_KINDS:
            found.append(f"Unknown normalization {kind!r}.")
        elif kind == "area" and self.normalization.get("target_area") is None:
            found.append("Area normalization needs a target_area.")
        if kind == "area" and self.resolved_flow_rate is None:
            found.append("Area normalization needs a flow rate.")

        if not hasattr(difference, self.metric):
            found.append(f"Unknown metric {self.metric!r}.")

        unknown = [c for c in self.components or () if c not in self.recipe.components]
        if unknown:
            found.append(f"Components {unknown} are not in the recipe {self.recipe.components}.")

        check = process_builder.check_recipe(self.recipe, self.overrides)
        if check.error is not None:
            found.append(f"Recipe cannot be built: {check.error}")
        else:
            unit, _, port = self.solution_path.partition(".")
            if unit not in check.units or port.split(".")[0] not in ("inlet", "outlet"):
                found.append(
                    f"Solution path {self.solution_path!r} is not in the process; units: "
                    f"{list(check.units)}."
                )
        return found


def _sum_components(metric: Any, components: Optional[list]) -> None:
    """Compare `metric` against the summed concentration of `components` (all if `None`).

    `setup_comparators` exposes no total-concentration switch. The reference is a
    single measured trace, so it is re-sliced before `components` is set, which from
    then on only selects the simulated components.
    """
    metric.use_total_concentration = True
    metric.reference = metric.reference_original
    metric.components = list(components) if components is not None else None
