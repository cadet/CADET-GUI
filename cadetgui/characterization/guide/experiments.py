"""Experiment types: what a lab run implies for the recipe, observation and parameter store."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ...instrument.recipes import template_fields
from ...instrument.starting_values import with_starting_values
from ...instrument.system import BYPASSABLE_UNITS
from ...instrument.templates import PARAMS
from ...io.configuration_store import ConfigurationState, InstrumentState
from ...io.experimental_data import ExperimentalRun
from ..comparison import Comparison
from ..parameter_store import Entry, ParameterSpec, ParameterStore, Provenance
from ..runner import StepSetup
from .roles import LARGE_TRACER, PROTEIN, SALT, SMALL_TRACER, SYSTEM_TRACER

_LWE = "Load–Wash–Elute (LWE)"
_INITIAL_STATE = ("c", "cp", "q")
_SMA = "Steric Mass Action (SMA)"


@dataclass(frozen=True)
class ImpliedValue:
    """A value an experiment type fixes by assumption; species-indexed ones go to the probe."""

    path: str
    value: float
    species_indexed: bool
    note: str


@dataclass(frozen=True)
class ExperimentType:
    """One kind of lab run and what it implies for the recipe, observation and store.

    `bypass` units are taken out of the flow path, `in_line` units are put back even if
    the base recipe bypassed them. `binding_key` replaces the base recipe's binding model.
    `with_salt` puts `SALT` in front of the probe component (SMA needs salt as component 0).
    The base recipe's initial column state is dropped; binding values that are missing
    or zero and the method of a salt-first binding model come from the shared starting
    values (`starting_values.with_starting_values`).
    `marker_keywords` are searched, in order, in the run-log markers to find the injection.
    `probe_roles` are the `COMPONENT_ROLES` a probe of this type may have; the first is
    the one a new component gets.
    """

    id: str
    label: str
    what_you_run: str
    step_id: str
    probe_role: str
    detector: str
    template_key: str
    solution_path: str
    normalization: str
    bypass: Tuple[str, ...]
    in_line: Tuple[str, ...]
    binding_key: str
    with_salt: bool = False
    sample_loop: bool = True
    marker_keywords: Tuple[str, ...] = ("inject", "sample", "elution")
    help: str = ""
    implied: Tuple[ImpliedValue, ...] = ()
    probe_roles: Tuple[str, ...] = ()

    def components(self, component: str) -> List[str]:
        """Return the recipe's component list for probe `component`."""
        if component == SALT and self.with_salt:
            raise ValueError(f"{SALT!r} is reserved for the salt component of {self.label!r}.")
        return [SALT, component] if self.with_salt else [component]

    def apply(self, base_recipe: ConfigurationState, *, component: str) -> ConfigurationState:
        """Return `base_recipe` set up for this experiment with the single probe `component`."""
        components = self.components(component)
        instrument = base_recipe.instrument or InstrumentState()
        bypass = (set(instrument.bypass_units) | set(self.bypass)) - set(self.in_line)
        instrument = replace(
            instrument,
            bypass_units=[u for u in BYPASSABLE_UNITS if u in bypass],
            include_sample_loop=self.sample_loop,
        )
        same_binding = self.binding_key == base_recipe.binding_key
        return with_starting_values(replace(
            base_recipe,
            components=components,
            binding_key=self.binding_key,
            template_key=self.template_key,
            instrument=instrument,
            column_values={
                k: v for k, v in map_species(
                    base_recipe.column_values, base_recipe.components, components
                ).items() if k not in _INITIAL_STATE
            },
            binding_values=(
                map_species(base_recipe.binding_values, base_recipe.components, components)
                if same_binding else {}
            ),
            model_values=self._model_values(base_recipe, components),
        ))

    def _model_values(
        self, base: ConfigurationState, components: List[str]
    ) -> Dict[str, Any]:
        base_values = dict(base.model_values)
        if "flow_rate" in base_values:
            base_values.setdefault("flow_rate_wash", base_values["flow_rate"])
        if "flow_rate_wash" in base_values:
            base_values.setdefault("flow_rate", base_values["flow_rate_wash"])

        fields = {f.name: f for f in template_fields(self.template_key, components)}
        values = {k: v for k, v in base_values.items() if k in fields and not _is_list(v)}
        probe = components[-1]

        def species(key: str, name: str, fallback: float) -> float:
            return _species_value(base, key, name, fallback)

        def default(key: str) -> float:
            return float(fields[key].default[0])

        for key in ("c_buffer_a", "c_buffer_b", "c_sample"):
            if key not in fields:
                continue
            if self.with_salt:
                if key == "c_sample":
                    fallback = values["c_buffer_a"][0] if "c_buffer_a" in values else default(key)
                    values[key] = [species(key, SALT, fallback), species(key, probe, 1.0)]
                else:
                    values[key] = [species(key, SALT, default(key)), species(key, probe, 0.0)]
            elif key == "c_sample":
                values[key] = [species(key, probe, _first_positive(base, key, 1.0))]
            else:
                values[key] = [0.0]
        return values

    def store_entries(self, component: str) -> Dict[str, Entry]:
        """Return the values this experiment type implies for probe `component`."""
        return {
            item.path: Entry(
                value={component: item.value} if item.species_indexed else item.value,
                provenance=Provenance(
                    step=f"assumed: {self.id}", probe=component, note=item.note
                ),
            )
            for item in self.implied
        }


def _is_list(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _species_value(base: ConfigurationState, key: str, name: str, fallback: float) -> float:
    values = base.model_values.get(key)
    if _is_list(values) and name in base.components and len(values) == len(base.components):
        return float(values[base.components.index(name)])
    return fallback


def _first_positive(base: ConfigurationState, key: str, fallback: float) -> float:
    values = base.model_values.get(key)
    positive = [float(v) for v in values if float(v) > 0] if _is_list(values) else []
    return positive[-1] if positive else fallback


def map_species(
    values: Mapping[str, Any], old: Sequence[str], new: Sequence[str]
) -> Dict[str, Any]:
    """Re-key per-component lists from `old` to `new` components by name.

    A single-component list is broadcast; a list that can't be mapped is dropped so the
    field falls back to its default.
    """
    out: Dict[str, Any] = {}
    for key, value in values.items():
        if not _is_list(value) or len(value) != len(old):
            out[key] = value
        elif all(name in old for name in new):
            out[key] = [value[list(old).index(name)] for name in new]
        elif len(value) == 1:
            out[key] = [value[0]] * len(new)
    return out


_PERIPHERY_LUMPING = (
    "Every dead volume between the sample loop and the detector (pre-column tubing, "
    "valves, the empty column holder or union, post-column tubing) is lumped into one "
    "tube, the pre-column tubing. Its fitted length and dispersion therefore stand for "
    "the whole extra-column volume, not for a physical piece of tubing."
)

_COLUMN_PULSE = ("tubing_pre_injection", "tubing_post_column")

EXPERIMENT_TYPES: Dict[str, ExperimentType] = {
    t.id: t for t in (
        ExperimentType(
            id="system_pulse",
            label="System pulse (no column in line)",
            what_you_run=(
                "Replace the column by a zero-dead-volume union and inject a small, non-"
                "interacting tracer (e.g. acetone or salt) from the sample loop. Record the "
                "detector signal of the tracer."
            ),
            step_id="system_periphery",
            probe_roles=(SMALL_TRACER, SYSTEM_TRACER),
            probe_role="tracer",
            detector="UV",
            template_key="Pulse Injection",
            solution_path="tubing_pre_column.outlet",
            normalization="area",
            bypass=("tubing_pre_injection", "column", "tubing_post_column", "tubing_detectors"),
            in_line=("tubing_pre_column",),
            binding_key="None",
            help=_PERIPHERY_LUMPING,
        ),
        ExperimentType(
            id="column_pulse_small_tracer",
            label="Column pulse, small tracer (conductivity)",
            what_you_run=(
                "With the column in line, inject a small tracer that enters the pores but "
                "does not bind (e.g. salt or acetone). Read it on the conductivity cell, "
                "which sits after the UV cell."
            ),
            step_id="column_packing",
            probe_roles=(SMALL_TRACER,),
            probe_role="small tracer (enters pores)",
            detector="conductivity",
            template_key="Pulse Injection",
            solution_path="tubing_detectors.outlet",
            normalization="area",
            bypass=_COLUMN_PULSE,
            in_line=("tubing_pre_column", "column", "tubing_detectors"),
            binding_key="None",
            help=(
                "The conductivity cell is observed after the detector tubing, the short "
                "volume between the UV and conductivity cells. Its size is known hardware "
                "and belongs in the parameter store before this step."
            ),
        ),
        ExperimentType(
            id="column_pulse_large_tracer",
            label="Column pulse, large tracer (UV)",
            what_you_run=(
                "With the column in line, inject a large tracer that is excluded from the "
                "pores (e.g. dextran or a large non-binding protein). Read it on the UV cell "
                "directly after the column."
            ),
            step_id="column_packing",
            probe_roles=(LARGE_TRACER,),
            probe_role="large tracer (excluded from pores)",
            detector="UV",
            template_key="Pulse Injection",
            solution_path="column.outlet",
            normalization="area",
            bypass=(*_COLUMN_PULSE, "tubing_detectors"),
            in_line=("tubing_pre_column", "column"),
            binding_key="None",
            help=(
                "A pore-excluded tracer sees only the space between the beads. The model "
                "expresses this by setting its film diffusion to zero, which is an "
                "assumption of this experiment type, not a fitted value."
            ),
            implied=(
                ImpliedValue(
                    "flow_sheet.column.film_diffusion", 0.0, True,
                    "assumed by the experiment type: a large tracer is excluded from the pores",
                ),
            ),
        ),
        ExperimentType(
            id="nonbinding_protein_pulse",
            label="Non-binding protein pulse",
            what_you_run=(
                "With the column in line, inject the protein under conditions where it does "
                "not bind (e.g. high salt). Read it on the UV cell after the column."
            ),
            step_id="particle_transport",
            probe_roles=(PROTEIN,),
            probe_role="non-binding protein",
            detector="UV",
            template_key="Pulse Injection",
            solution_path="column.outlet",
            normalization="area",
            bypass=(*_COLUMN_PULSE, "tubing_detectors"),
            in_line=("tubing_pre_column", "column"),
            binding_key="None",
            help=(
                "Peak broadening beyond what the packing explains comes from mass transfer "
                "into the beads, which this run determines as film diffusion."
            ),
        ),
        ExperimentType(
            id="linear_gradient_elution",
            label="Linear gradient elution",
            what_you_run=(
                "Load a small amount of protein at low salt, wash, then elute with a linear "
                "salt gradient from buffer A to buffer B. Read the protein on UV."
            ),
            step_id="binding",
            probe_roles=(PROTEIN,),
            probe_role="binding protein",
            detector="UV",
            template_key=_LWE,
            solution_path="column.outlet",
            normalization="area",
            bypass=(*_COLUMN_PULSE, "tubing_detectors"),
            in_line=("tubing_pre_column", "column"),
            binding_key=_SMA,
            with_salt=True,
            marker_keywords=("inject", "sample", "load"),
            help=(
                "Binding is modelled with steric mass action, so salt is component 0 and "
                "the protein component 1. Where the protein elutes in the gradient "
                "determines its characteristic charge and equilibrium constant."
            ),
        ),
        ExperimentType(
            id="breakthrough",
            label="Breakthrough",
            what_you_run=(
                "Pump protein feed continuously onto the equilibrated column until the "
                "outlet reaches the feed concentration. Read the protein on UV."
            ),
            step_id="capacity",
            probe_roles=(PROTEIN,),
            probe_role="binding protein",
            detector="UV",
            template_key="Breakthrough",
            solution_path="column.outlet",
            normalization="none",
            bypass=(*_COLUMN_PULSE, "tubing_detectors"),
            in_line=("tubing_pre_column", "column"),
            binding_key=_SMA,
            with_salt=True,
            sample_loop=False,
            marker_keywords=("load", "sample", "feed"),
            help=(
                "The breakthrough curve is compared in concentration units, so the UV "
                "signal must be converted to concentration; area normalization does not "
                "apply to a curve that never returns to baseline."
            ),
        ),
    )
}


def with_implied_values(
    store: ParameterStore, experiment_type: ExperimentType, component: str
) -> ParameterStore:
    """Return `store` plus the values `experiment_type` implies for `component`."""
    for path, entry in experiment_type.store_entries(component).items():
        item = next(i for i in experiment_type.implied if i.path == path)
        specs = {} if path in store.specs else {path: ParameterSpec(path, item.species_indexed)}
        store = store.updated({path: entry.value}, entry.provenance, specs=specs)
    return store


def missing_assumptions(
    setup: StepSetup, store: ParameterStore
) -> List[Tuple[Comparison, str, float]]:
    """Return `(comparison, path, value)` for experiment-type assumptions `store` lacks."""
    missing = []
    for comparison in setup.comparisons:
        experiment = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
        if experiment is None or not comparison.probe:
            continue
        for item in experiment.implied:
            value = store.entries[item.path].value if item.path in store else None
            if item.species_indexed:
                present = isinstance(value, dict) and comparison.probe in value
            else:
                present = value is not None
            if not present:
                missing.append((comparison, item.path, item.value))
    return missing


def record_assumptions(setup: StepSetup, store: ParameterStore) -> ParameterStore:
    """Return `store` plus the values the step's experiment types assume and it lacks.

    Species gaps are judged on this store, so an assumed value is never covered by a
    species transfer.
    """
    for comparison, _path, _value in missing_assumptions(setup, store):
        store = with_implied_values(
            store, EXPERIMENT_TYPES[comparison.experiment_type], comparison.probe
        )
    return store


def find_injection_marker(
    run: ExperimentalRun, keywords: Sequence[str] = ("inject", "sample", "elution")
) -> Optional[str]:
    """Return the first run-log marker containing a keyword, trying keywords in order."""
    for keyword in keywords:
        for _, text in run.markers:
            if keyword in text.lower():
                return text
    return None


def measurement_from_run(
    name: str,
    run: ExperimentalRun,
    channel: str,
    experiment_type: ExperimentType,
    base_recipe: ConfigurationState,
    *,
    component: str,
    flow_rate: Optional[float] = None,
    injection_marker: Optional[str] = None,
) -> Comparison:
    """Build a comparison from lab choices: run, channel, experiment type and probe name.

    Without `injection_marker`, the first marker matching the experiment type's keywords is
    used. Area normalization targets the injected amount (sample concentration times loop
    volume).
    """
    recipe = experiment_type.apply(base_recipe, component=component)
    if flow_rate is None and "flow_rate" not in recipe.model_values:
        flow_rate = float(
            recipe.model_values.get("flow_rate_wash", PARAMS["flow_rate_wash"].default)
        )
    if injection_marker is None:
        injection_marker = find_injection_marker(run, experiment_type.marker_keywords)

    normalization: Dict[str, Any] = {"kind": "none"}
    if experiment_type.normalization == "area":
        c_sample = recipe.model_values["c_sample"][recipe.components.index(component)]
        normalization = {
            "kind": "area",
            "target_area": float(c_sample) * float(recipe.instrument.sample_loop_volume),
        }

    return Comparison(
        name=name,
        data_file=run.label,
        channel=channel,
        recipe=recipe,
        solution_path=experiment_type.solution_path,
        flow_rate=flow_rate,
        injection_marker=injection_marker,
        normalization=normalization,
        components=[component],
        probe=component,
        experiment_type=experiment_type.id,
        run=run,
    )
