"""The recommended characterization chain, its steps in lab terms, and matching a step to it."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..comparison import Comparison
from ..runner import StepSetup
from ..stages import STAGES


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


def step_title(step: StepSetup) -> str:
    """Return a step's chain title, or its own name for a custom step."""
    guide = guide_for_step(step)
    return guide.title if guide is not None else step.name


def guide_measurements(study: Any, guide: ChainStepGuide) -> List[Comparison]:
    """Return the study's measurements whose experiment type feeds `guide`."""
    return [c for c in study.comparisons if c.experiment_type in guide.experiment_types]
