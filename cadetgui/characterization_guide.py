"""Lab-language guide to the characterization chain: experiment types, default chain, glossary.

An `ExperimentType` says what a lab run implies for the model: which units are in the
flow path, which process template, which component, where the detector sits, which
chain step it feeds and which values it fixes by assumption. `DEFAULT_CHAIN` is the
recommended order of steps with plain-language docs per step. Headless (no ipywidgets).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from CADETProcess.processModel import ComponentSystem

from .cadetprocessadapter import (
    BYPASSABLE_UNITS,
    INSTRUMENT_TEMPLATES,
    PARAMS,
    UNIT_LABELS,
)
from .characterization_runner import StepSetup
from .characterization_stages import STAGES, VariableDef, describe_stage
from .comparison import Comparison
from .configuration_store import ConfigurationState, InstrumentState
from .experimental_data import ExperimentalRun
from .parameter_store import (
    Entry,
    ParameterSpec,
    ParameterStore,
    Provenance,
    has_parameter,
    read_process,
    spec_for,
)
from .parameters import get_parameters
from .process_builder import check_recipe
from .starting_values import with_starting_values

__all__ = [
    "parameter_unit",
    "SALT",
    "COMPONENT_ROLES",
    "SYSTEM_TRACER",
    "SMALL_TRACER",
    "LARGE_TRACER",
    "PROTEIN",
    "SALT_ROLE",
    "Determined",
    "ImpliedValue",
    "ExperimentType",
    "EXPERIMENT_TYPES",
    "ChainStepGuide",
    "DEFAULT_CHAIN",
    "CHAIN_BY_ID",
    "GLOSSARY",
    "GLOSSARY_ALIASES",
    "WORKFLOW_GUIDE",
    "new_step_setup",
    "with_implied_values",
    "missing_assumptions",
    "record_assumptions",
    "measurement_from_run",
    "map_species",
    "find_injection_marker",
    "guide_for_step",
    "parameter_label",
    "species_gap_messages",
    "guide_measurements",
    "role_fix",
    "option_label",
    "option_help",
    "STEP_TYPE_HELP",
    "step_type_help",
    "step_summary",
    "StartingValue",
    "starting_values",
]

SALT = "Salt"

SYSTEM_TRACER = "system tracer"
SMALL_TRACER = "small tracer"
LARGE_TRACER = "large tracer"
PROTEIN = "protein"
SALT_ROLE = "salt"

COMPONENT_ROLES: Dict[str, str] = {
    SYSTEM_TRACER: "A non-interacting tracer used only for system pulses (column replaced "
    "by a union). A small tracer such as acetone does both jobs: declare it as a small "
    "tracer instead.",
    SMALL_TRACER: "A small non-binding tracer that enters the bead pores (e.g. acetone or "
    "salt pulse). Also serves as the tracer of system pulses.",
    LARGE_TRACER: "A large non-binding tracer that is excluded from the pores (e.g. "
    "dextran).",
    PROTEIN: "The protein you characterize: non-binding pulses, gradient elution and "
    "breakthrough.",
    SALT_ROLE: "The salt of gradient and breakthrough runs; component 0 of steric mass "
    "action. Its name is fixed to \"" + SALT + "\".",
}

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

        fields = {f.name: f for f in _template_fields(self.template_key, components)}
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


def _template_fields(template_key: str, components: Sequence[str]) -> list:
    """Return the instrument template's form fields for `components`, without a flow sheet."""
    stub = SimpleNamespace(component_system=ComponentSystem(list(components)))
    return INSTRUMENT_TEMPLATES[template_key](stub).fields


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


@dataclass(frozen=True)
class Determined:
    """One parameter a step determines: its name, what it means physically, and its unit."""

    name: str
    meaning: str
    unit: str


@dataclass(frozen=True)
class ChainStepGuide:
    """One recommended chain step, described in lab terms.

    `system_units` are the flow-sheet units whose parameters this step determines;
    `requires` are parameter paths earlier steps must have provided; `known_values` are
    hardware parameter paths that must be known (in the parameter store or set in the
    recipe) before the fit. Both are checked live (`step_checks.step_checks`); `advice`
    holds what the software cannot check.
    """

    id: str
    title: str
    purpose: str
    stage: str
    options: Mapping[str, Any]
    determines: Tuple[Determined, ...]
    system_units: Tuple[str, ...]
    experiment_types: Tuple[str, ...]
    advice: Tuple[str, ...]
    reading_results: str
    requires: Tuple[str, ...] = ()
    known_values: Tuple[str, ...] = ()


_TUBING = ("flow_sheet.tubing_pre_column.length", "flow_sheet.tubing_pre_column.axial_dispersion")
_BED = (
    "flow_sheet.column.bed_porosity",
    "flow_sheet.column.particle_porosity",
    "flow_sheet.column.axial_dispersion",
)
_FILM = ("flow_sheet.column.film_diffusion",)
_SMA_EQ = (
    "flow_sheet.column.binding_model.characteristic_charge",
    "flow_sheet.column.binding_model.adsorption_rate",
)

_READING_PARETO = (
    "Each measurement is one objective, so the fit returns a set of Pareto candidates: "
    "parameter sets where no measurement can be matched better without matching another "
    "worse. 'Best average' has the lowest mean NRMSE and is the usual choice when the "
    "replicates agree. If one candidate is best for one run only, look at that run's "
    "chart: an outlier run (bad baseline, wrong marker) pulls its own candidate away, "
    "and fixing the measurement is better than accepting it."
)

DEFAULT_CHAIN: Tuple[ChainStepGuide, ...] = (
    ChainStepGuide(
        id="system_periphery",
        title="Extra-column volume",
        purpose="How much the system itself delays and spreads a pulse, without a column.",
        stage="tubing",
        options={"tubing": "tubing_pre_column"},
        determines=(
            Determined(
                "Pre-column tubing length",
                "Dead volume between sample loop and detector, expressed as a tubing length",
                "m",
            ),
            Determined("Tubing axial dispersion", "Band broadening in that dead volume", "m²/s"),
        ),
        system_units=("tubing_pre_column",),
        experiment_types=("system_pulse",),
        advice=(
            "The baseline before the peak is flat, or a baseline window is set in the "
            "measurement.",
            "The tracer does not interact with the tubing (a symmetric, fully recovered peak).",
        ),
        reading_results=_READING_PARETO,
        known_values=("flow_sheet.tubing_pre_column.diameter",),
    ),
    ChainStepGuide(
        id="column_packing",
        title="Column packing",
        purpose="How the packed bed is built: space between beads, space inside beads, "
        "and band broadening along the column.",
        stage="bed",
        options={"include_particle_porosity": True},
        determines=(
            Determined("Bed porosity", "Volume fraction between the beads", "–"),
            Determined("Particle porosity", "Pore volume fraction inside a bead", "–"),
            Determined("Column axial dispersion", "Band broadening in the packed bed", "m²/s"),
        ),
        system_units=("column",),
        experiment_types=("column_pulse_small_tracer", "column_pulse_large_tracer"),
        advice=(
            "Baselines are flat, or a baseline window is set in each measurement.",
            "The large tracer is really excluded from the pores (e.g. a dextran well above "
            "the resin's exclusion limit).",
        ),
        reading_results=_READING_PARETO + (
            " The small tracer sets the total porosity, the large tracer the bed porosity; "
            "a candidate that fits one tracer only usually trades one porosity for the other."
        ),
        requires=_TUBING,
        known_values=(
            "flow_sheet.column.length",
            "flow_sheet.column.diameter",
            "flow_sheet.tubing_detectors.length",
            "flow_sheet.tubing_detectors.diameter",
        ),
    ),
    ChainStepGuide(
        id="particle_transport",
        title="Particle transport",
        purpose="How fast a protein moves from the liquid between the beads into the pores.",
        stage="particles",
        options={"include_film_diffusion": True},
        determines=(
            Determined("Film diffusion", "Mass transfer of the protein into the beads", "m/s"),
        ),
        system_units=("column",),
        experiment_types=("nonbinding_protein_pulse",),
        advice=(
            "The protein does not bind under the run conditions (full recovery).",
            "Baselines are flat, or a baseline window is set in each measurement.",
        ),
        reading_results=_READING_PARETO,
        requires=(*_TUBING, *_BED),
        known_values=("flow_sheet.column.particle_radius",),
    ),
    ChainStepGuide(
        id="binding",
        title="Binding",
        purpose="How strongly the protein binds and how its binding depends on salt.",
        stage="adsorption",
        options={"component_index": 1},
        determines=(
            Determined("Characteristic charge", "Number of binding sites the protein uses", "–"),
            Determined(
                "Equilibrium constant",
                "Binding strength, as adsorption rate with desorption fixed at 1",
                "–",
            ),
        ),
        system_units=("column",),
        experiment_types=("linear_gradient_elution",),
        advice=(
            "Gradients of different slopes are attached; one slope cannot separate charge "
            "from equilibrium constant.",
            "The protein is loaded well below capacity, so the peak position does not "
            "depend on the load.",
        ),
        reading_results=_READING_PARETO + (
            " Compare peak positions first; peak shape depends on transport values fitted "
            "earlier."
        ),
        requires=(*_TUBING, *_BED, *_FILM),
        known_values=("flow_sheet.column.binding_model.capacity",),
    ),
    ChainStepGuide(
        id="capacity",
        title="Capacity",
        purpose="How much protein the column holds before it breaks through.",
        stage="capacity",
        options={},
        determines=(
            Determined("Ionic capacity", "Binding sites of the resin", "mol/m³ solid phase"),
        ),
        system_units=("column",),
        experiment_types=("breakthrough",),
        advice=(
            "The UV signal is converted to concentration (or the detector is in its linear "
            "range and scaled).",
            "The run continues until the outlet reaches the feed concentration.",
        ),
        reading_results=_READING_PARETO,
        requires=(*_TUBING, *_BED, *_FILM, *_SMA_EQ),
    ),
)

CHAIN_BY_ID: Dict[str, ChainStepGuide] = {g.id: g for g in DEFAULT_CHAIN}

GLOSSARY: Dict[str, str] = {
    "measurement": "One recorded run: a data file with one or more detector channels.",
    "characterization step": "One fit of one part of the system (e.g. the extra-column "
    "volume or the column packing) to the measurements that belong to it. Steps run in "
    "chain order; each starts from the values accepted before it.",
    "step type": "What a step fits and how the model represents it, e.g. the length and "
    "dispersion of one tubing segment or the porosities of the column bed. A step of the "
    "recommended chain sets it for you.",
    "extra-column volume": "All the liquid volume a sample passes outside the packed bed "
    "(tubing, valves, mixer, detector cells). It delays and broadens every peak, so it is "
    "characterized first, with a system pulse and no column in line.",
    "comparison": "A measurement paired with the recipe that should reproduce it, the "
    "channel and observation point to compare, and how to align and scale the trace. The "
    "workbench lists each comparison as a measurement.",
    "experiment type": "The kind of lab run (e.g. system pulse, breakthrough); it fixes the "
    "flow path, process template, observation point and which step the run feeds.",
    "recipe": "Everything a fresh simulation of one run is built from: the system (hardware, "
    "flow rate, column and binding model), the components and the method (process "
    "template) of the run's experiment type. It holds no fitted values.",
    "flow path": "The units the liquid passes through in a run; units not used in that run "
    "are bypassed.",
    "observation point": "Where in the flow path the simulated signal is read, matching the "
    "detector's position (e.g. column outlet for UV).",
    "injection marker": "A run-log entry (e.g. 'Phase Elution') marking when the sample was "
    "injected; used to align the measured clock to the simulated one.",
    "alignment": "Shifting the measured trace in time so its injection coincides with the "
    "simulated injection.",
    "baseline window": "A stretch of the run without signal from the probe, used to "
    "estimate and subtract the detector baseline.",
    "normalization": "Scaling the measured trace, e.g. so its peak area equals the injected "
    "amount; removes the unknown detector response factor.",
    "prior": "The parameter values a step starts from: everything accepted before it.",
    "posterior": "The parameter values a step ends with, once a candidate is accepted.",
    "parameter store": "The accepted and known parameter values of the whole chain, each "
    "with its provenance.",
    "provenance": "Where a stored value came from: the step, the probe, the runs, the "
    "metric, or a note if it was assumed.",
    "probe": "The substance injected to measure something (tracer, protein).",
    "component": "A molecule you inject or elute with (tracer, protein, salt), declared "
    "once for the study with its role. Each measurement picks its probe from the declared "
    "components, and fitted values are stored under the component's name, so the same "
    "name links values across steps.",
    "component role": "What a component is in the lab: system tracer, small tracer, large "
    "tracer, protein or salt. The role decides which experiment types may use it.",
    **COMPONENT_ROLES,
    "species transfer": "Explicitly reusing a value measured with one probe for another "
    "(e.g. system dispersion measured with acetone, reused for a protein); recorded as an "
    "assumption.",
    "Pareto candidate": "A fitted parameter set that no other set beats on every "
    "measurement at once.",
    "best average": "The Pareto candidate with the lowest mean error over all measurements.",
    "fitted variable": "A parameter the optimizer searches between a lower and an upper "
    "bound; the value of the candidate you accept is written to the parameter store.",
    "fixed variable": "A parameter a step could fit but is told to keep at its current "
    "value (from an earlier step, the starting parameters or the recipe): its Fit box is "
    "unticked. Use it when the measurements cannot separate two parameters.",
    "NRMSE": "Normalized root-mean-square error between simulated and measured traces; "
    "0 is a perfect match.",
}

GLOSSARY_ALIASES: Dict[str, str] = {"frozen variable": "fixed variable"}
"""Older glossary terms and the entry they resolve to."""

WORKFLOW_GUIDE = """\
# Characterizing a column, step by step

1. **System.** Describe the instrument once: which tubing, mixer and sample loop are
   installed, the known hardware values (tubing diameters, loop volume) and the flow rate
   your runs use; under Advanced configuration, the column and binding model with their
   starting values. This is the base every run starts from. The method (which inlets
   pump, when the loop injects, which units are bypassed) is not part of the system: it
   comes with each measurement's experiment type.
2. **Components.** On the System page, above the hardware, declare the molecules you
   inject or elute with and give each a role (system tracer, small tracer, large tracer,
   protein, salt). Use the same name for the same molecule in every step: fitted values
   are kept per component and reused only under that name. To use a value for another
   molecule (e.g. a tracer's dispersion for your protein), copy it on the step page with
   "Transfer to this step's species" (a species transfer).
3. **Measurements.** Load each run's export. For every run choose its experiment type
   (e.g. "System pulse (no column in line)"), its component and the detector channel;
   the experiment type sets the method (process template), the units the run bypasses
   and the observation point for you.
   Check the injection marker, baseline window and normalization on its measured trace.
4. **Steps, in order.** Work through the chain: Extra-column volume, Column packing,
   Particle transport, Binding, Capacity. For each step, add its measurements first,
   then set the step up from Setup. A step fits one part of the system from its
   measurements; its page lists what it determines and which experiment types feed it.
   Steps run in order, each starting from the values accepted before it, so only start a
   step once the steps before it are accepted.
5. **Before each fit.** Go through the step's "Before you run" checks; each open item
   has a button to fix it, e.g. carrying values measured with one probe over to this
   step's probes (species transfer).
6. **Fit and choose.** Run the fit. Each measurement is one objective; from the Pareto
   candidates pick one, usually "best average", after checking the per-run charts.
7. **Accept.** Accepting writes the chosen values into the parameter store with their
   provenance; the next step starts from there.
8. **Result.** After the last step, the parameter store holds the accepted parameters of
   the whole system, ready to simulate new processes.
"""


def new_step_setup(guide: ChainStepGuide, comparisons: Sequence[Comparison]) -> StepSetup:
    """Return a `StepSetup` named `guide.title` for `guide` fitting `comparisons`.

    Raises if a comparison's experiment type feeds a different step.
    """
    wrong = [
        c.name for c in comparisons
        if c.experiment_type is not None and c.experiment_type not in guide.experiment_types
    ]
    if wrong:
        raise ValueError(
            f"Measurements {wrong} are experiment types that do not feed {guide.title!r}."
        )
    return StepSetup(
        name=guide.title,
        stage=guide.stage,
        options=dict(guide.options),
        comparisons=list(comparisons),
        requires=tuple(guide.requires),
    )


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


def _resolved_options(stage: str, options: Mapping[str, Any]) -> Dict[str, Any]:
    params = STAGES[stage].options
    return {
        name: options.get(name, param.default)
        for name, param in params.items()
        if name in options or param.default is not inspect.Parameter.empty
    }


def guide_for_step(step: StepSetup) -> Optional[ChainStepGuide]:
    """Return the chain guide `step` follows.

    Matched by name (the guide's id or title), else by the same stage and options.
    """
    if step.name in CHAIN_BY_ID:
        return CHAIN_BY_ID[step.name]
    by_title = next((g for g in DEFAULT_CHAIN if g.title == step.name), None)
    if by_title is not None:
        return by_title
    options = _resolved_options(step.stage, step.options)
    for guide in DEFAULT_CHAIN:
        if guide.stage == step.stage and _resolved_options(guide.stage, guide.options) == options:
            return guide
    return None


def _step_title(step: StepSetup) -> str:
    guide = guide_for_step(step)
    return guide.title if guide is not None else step.name


def parameter_label(path: str) -> str:
    """Return a lab label for a store path, e.g. "film diffusion (Column)"."""
    parts = path.split(".")
    name = parts[-1].replace("_", " ")
    if len(parts) > 2 and parts[0] == "flow_sheet":
        return f"{name} ({UNIT_LABELS.get(parts[1], parts[1])})"
    return name


def _source_text(study: Any, step: Optional[str]) -> str:
    if not step or step == "initial":
        return "the starting values hold it"
    if step.startswith("assumed: "):
        experiment = EXPERIMENT_TYPES.get(step.partition(": ")[2])
        return f"{experiment.label if experiment else step} assumes it"
    setup = next((s for s in study.steps if s.name == step), None)
    if setup is not None:
        return f"{_step_title(setup)} fitted it"
    return f"step {step} set it"


def species_gap_messages(
    study: Any, step: StepSetup, gaps: Mapping[str, Sequence[str]], store: ParameterStore
) -> List[str]:
    """Return one line per gap naming the components that lack a value and who set it.

    E.g. "Binding needs film diffusion (Column) for IgG; Particle transport fitted it for
    BSA", without a closing period.
    """
    title = _step_title(step)
    lines = []
    for path, names in gaps.items():
        entry = store.entries[path]
        lines.append(
            f"{title} needs {parameter_label(path)} for {', '.join(names)}; "
            f"{_source_text(study, entry.provenance.step)} for "
            f"{', '.join(sorted(entry.value)) or 'no component'}"
        )
    return lines


def guide_measurements(study: Any, guide: ChainStepGuide) -> List[Comparison]:
    """Return the study's measurements whose experiment type feeds `guide`."""
    return [c for c in study.comparisons if c.experiment_type in guide.experiment_types]


def _a(role: str) -> str:
    return f"{'an' if role[:1] in 'aeiou' else 'a'} {role}"


def role_fix(
    study: Any, name: str, experiment_type: ExperimentType
) -> Tuple[str, Optional[str]]:
    """Return why component `name` does not fit `experiment_type` and the role to give it.

    The role is `experiment_type`'s first probe role, offered only when every other
    measurement using `name` as its probe accepts it too; otherwise the role is None and
    the text says which measurements need the current one. Returns `("", None)` when
    `name` fits or is not declared.
    """
    component = study.component(name)
    roles = experiment_type.probe_roles
    if component is None or not roles or component.role in roles:
        return "", None
    target = roles[0]
    text = (
        f"{name} is declared as {_a(component.role)}. This experiment needs {_a(target)}."
    )
    if component.role == SALT_ROLE:
        return text + " The salt keeps its role; pick another component.", None
    blockers = []
    for comparison in study.comparisons:
        used_as = EXPERIMENT_TYPES.get(comparison.experiment_type or "")
        if comparison.probe == name and used_as is not None and target not in used_as.probe_roles:
            blockers.append(f"{comparison.name} ({used_as.label})")
    if not blockers:
        return text, target
    return text + (
        f" Its role cannot change: {', '.join(blockers)} use{'s' * (len(blockers) == 1)} it "
        f"as {_a(component.role)} and need{'s' * (len(blockers) == 1)} that role. Pick "
        f"another component, or name a new one (e.g. \"{name} {target}\")."
    ), None


_OPTION_LABELS: Dict[str, str] = {
    "tubing": "Tubing segment",
    "component_index": "Component",
    "is_kinetic": "Kinetic binding",
    "include_particle_porosity": "Fit particle porosity",
    "include_axial_dispersion": "Fit column axial dispersion",
    "include_film_diffusion": "Fit film diffusion",
    "include_pore_diffusion": "Fit pore diffusion",
    "include_steric_factor": "Fit steric factor",
}

_OPTION_HELP: Dict[str, str] = {
    "tubing": "The tubing whose length and axial dispersion are fitted. One segment stands "
    "in for the whole extra-column volume: every dead volume between sample loop and "
    "detector is lumped into it, because a pulse cannot tell apart where along the flow "
    "path it was delayed and spread. Its fitted length is therefore not a physical length.",
    "component_index": "Which component's parameters are fitted. In steric mass action the "
    "salt is component 0, so the protein is usually component 1.",
    "is_kinetic": "Fit adsorption and desorption rates separately instead of only the "
    "equilibrium constant. Needs runs whose peak shape depends on binding kinetics.",
    "include_particle_porosity": "Also fit the pore volume fraction inside the beads. Needs "
    "a small tracer that enters the pores; a pore-excluded tracer alone cannot see it.",
    "include_axial_dispersion": "Also fit the band broadening along the column for this "
    "component; otherwise it keeps the value from an earlier step.",
    "include_film_diffusion": "Fit the film diffusion: how fast the component moves from "
    "the liquid between the beads into the pores.",
    "include_pore_diffusion": "Fit the pore diffusion: transport inside the pores. Only "
    "column models with pore diffusion (e.g. the general rate model) have it.",
    "include_steric_factor": "Also fit the steric shielding factor, which matters at high "
    "loading (e.g. breakthrough runs).",
}


STEP_TYPE_HELP: Dict[str, str] = {
    "tubing": "Delay and band broadening of one tubing segment (its length and axial "
    "dispersion), from pulses without a column.",
    "pre_injection": "Dead volume before the injection point, as the length of the "
    "pre-injection tubing and the volume of the mixer.",
    "bed": "How the column is packed: bed porosity, axial dispersion and optionally "
    "particle porosity, from non-binding tracer pulses through the column.",
    "particles": "How one component moves between and into the beads (film, pore or "
    "axial dispersion, as ticked), from non-binding pulses of that component.",
    "capacity": "The resin's ionic capacity, from breakthrough curves.",
    "adsorption": "Steric mass action binding of one component (characteristic charge and "
    "equilibrium constant), from gradient elutions of different slopes.",
}
"""One line per step type (`characterization_stages.STAGES` id) saying what it fits."""


def step_type_help(stage: str) -> str:
    """Return one line saying what a step of type `stage` fits."""
    return STEP_TYPE_HELP.get(stage, "")


def option_label(name: str) -> str:
    """Return a readable label for step-type option `name`."""
    return _OPTION_LABELS.get(name, name.replace("_", " ").capitalize())


def option_help(stage: str, name: str) -> str:
    """Return a one-line explanation of option `name` of step type `stage`."""
    if name in _OPTION_HELP:
        return _OPTION_HELP[name]
    label = STAGES[stage].label if stage in STAGES else stage
    return f"Setting {name!r} of the {label} fit, passed on to CADET-Process."


_UNIT_NOUNS: Dict[str, str] = {
    "tubing_pre_column": "pre-column tubing",
    "tubing_pre_injection": "pre-injection tubing",
    "tubing_post_column": "post-column tubing",
    "tubing_detectors": "tubing between the detectors",
}

_STAGE_SUMMARIES: Dict[str, str] = {
    "pre_injection": "Fits the dead volume before the injection point, represented as the "
    "length of the pre-injection tubing and the volume of the mixer.",
    "bed": "Fits how the column is packed: {parameters} of the column, from tracer pulses "
    "through the column.",
    "particles": "Fits how {component} moves between and into the beads: {parameters}.",
    "adsorption": "Fits the steric mass action binding of {component}: {parameters}.",
    "capacity": "Fits the resin's ionic capacity from breakthrough curves.",
}


def _joined(items: Sequence[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _component_name(setup: StepSetup, index: Any) -> str:
    components = setup.comparisons[0].recipe.components if setup.comparisons else []
    index = int(index or 0)
    return components[index] if index < len(components) else f"component {index}"


def step_summary(setup: StepSetup) -> str:
    """Return one plain sentence saying what `setup` fits and how the model represents it."""
    options = setup.options
    if setup.stage == "tubing":
        unit = options.get("tubing")
        noun = _UNIT_NOUNS.get(unit, UNIT_LABELS.get(unit, str(unit)).lower())
        if unit == "tubing_pre_column":
            return (
                "Fits the extra-column dead volume and its band broadening, represented as "
                f"the length and axial dispersion of the {noun}."
            )
        if not unit:
            return "Fits the length and axial dispersion of one tubing segment; pick it below."
        return (
            f"Fits the dead volume and band broadening of the {noun}, as its length and "
            "axial dispersion."
        )
    try:
        variables = describe_stage(setup.stage, **options)
    except (KeyError, ValueError) as exc:
        return f"Cannot describe this fit yet: {exc}"
    names = []
    for var in variables:
        if var.parameter_path is None:
            continue
        name = var.parameter_path.rsplit(".", 1)[-1].replace("_", " ")
        if var.name == "adsorption_rate" and not options.get("is_kinetic"):
            name = "equilibrium constant (adsorption rate at a desorption rate of 1)"
        if name not in names:
            names.append(name)
    template = _STAGE_SUMMARIES.get(setup.stage, "Fits {parameters}.")
    return template.format(
        parameters=_joined(names) if names else "nothing",
        component=_component_name(setup, options.get("component_index")),
    )


@dataclass(frozen=True)
class StartingValue:
    """The value a variable starts from: formatted `text`, LaTeX `unit` and its `source`."""

    text: str
    unit: str
    source: str


FROM_PROCESS = "from the process setup"
STARTING_VALUE = "starting value"
ASSUMED_BY_TYPE = "assumed by experiment type"


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        texts = {name: _value_text(v) for name, v in value.items()}
        if len(set(texts.values())) == 1:
            return next(iter(texts.values()))
        return "; ".join(f"{name}: {text}" for name, text in texts.items())
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value_text(v) for v in value) + "]"
    if hasattr(value, "tolist"):
        return _value_text(value.tolist())
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _owner(process: Any, path: str) -> Any:
    obj = process
    for part in path.rpartition(".")[0].split("."):
        if hasattr(obj, "__getitem__") and not hasattr(obj, part):
            obj = obj[part]
        else:
            obj = getattr(obj, part)
    return obj


def parameter_unit(process: Any, path: str) -> str:
    """Return the LaTeX unit CADET-Process declares for `path` on `process`, or ""."""
    owner = _owner(process, path)
    attribute = path.rpartition(".")[2]
    category = "binding" if ".binding_model." in f".{path}" else "column"
    try:
        return get_parameters(category, type(owner).__name__)[attribute].get("unit") or ""
    except KeyError:
        descriptor = getattr(type(owner), attribute, None)
        if isinstance(descriptor, property):
            descriptor = getattr(type(owner), f"_{attribute}", None)
        return getattr(descriptor, "unit", None) or ""


def _provenance_source(study: Any, step: Optional[str]) -> str:
    if not step or step == "initial":
        return STARTING_VALUE
    if step.startswith("assumed: "):
        return ASSUMED_BY_TYPE
    setup = next((s for s in study.steps if s.name == step), None)
    return f"from {_step_title(setup) if setup is not None else step}"


def _species_subset(value: Any, species: Sequence[str]) -> Any:
    if not isinstance(value, dict) or not species:
        return value
    picked = {name: value[name] for name in species if name in value}
    return picked or None


def starting_values(
    study: Any, setup: StepSetup, variables: Optional[Sequence[VariableDef]] = None
) -> Dict[str, StartingValue]:
    """Return, per variable of `setup` with a parameter path, the value its fit starts from.

    The value comes from the step's prior (`study.prior_for`, or the current store for a
    step not in the study), restricted to the measurements' components, labelled by its
    provenance ("from <step title>", `STARTING_VALUE`, `ASSUMED_BY_TYPE`). A path the
    prior lacks is read off the first measurement's built process (`FROM_PROCESS`).
    """
    if variables is None:
        variables = describe_stage(setup.stage, **setup.options)
    names = [s.name for s in study.steps]
    prior = study.prior_for(setup.name) if setup.name in names else study.current_store
    probes = list(dict.fromkeys(c.probe for c in setup.comparisons if c.probe))
    processes = []
    for comparison in setup.comparisons:
        check = check_recipe(comparison.recipe, comparison.overrides)
        if check.error is None:
            processes.append(check.process)

    values: Dict[str, StartingValue] = {}
    for var in variables:
        path = var.parameter_path
        if path is None:
            continue
        process = next((p for p in processes if has_parameter(p, path)), None)
        unit = parameter_unit(process, path) if process is not None else ""
        value, source = None, ""
        entry = prior.entries.get(path)
        if entry is not None:
            spec = prior.specs.get(path)
            value = entry.value
            if spec is not None and spec.species_indexed:
                value = _species_subset(value, probes)
            source = _provenance_source(study, entry.provenance.step)
        if value is None and process is not None:
            try:
                reader = ParameterStore(specs={path: spec_for(process, path)})
                value = read_process(process, [path], reader)[path]
            except KeyError:
                value = None
            else:
                picked = _species_subset(value, probes)
                value = value if picked is None else picked
                source = FROM_PROCESS
        if value is None:
            values[var.name] = StartingValue("—", unit, "not set")
        else:
            values[var.name] = StartingValue(_value_text(value), unit, source)
    return values
