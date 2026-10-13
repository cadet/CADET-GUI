"""Lab-language labels, help lines and messages for steps, options, parameters and roles."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ...instrument.system import UNIT_LABELS
from ..parameter_store import ParameterStore
from ..runner import StepSetup
from ..stages import STAGES, describe_stage
from .chain import step_title
from .experiments import EXPERIMENT_TYPES, ExperimentType
from .roles import SALT_ROLE


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
        return f"{step_title(setup)} fitted it"
    return f"step {step} set it"


def species_gap_messages(
    study: Any, step: StepSetup, gaps: Mapping[str, Sequence[str]], store: ParameterStore
) -> List[str]:
    """Return one line per gap naming the components that lack a value and who set it.

    E.g. "Binding needs film diffusion (Column) for IgG; Particle transport fitted it for
    BSA", without a closing period.
    """
    title = step_title(step)
    lines = []
    for path, names in gaps.items():
        entry = store.entries[path]
        lines.append(
            f"{title} needs {parameter_label(path)} for {', '.join(names)}; "
            f"{_source_text(study, entry.provenance.step)} for "
            f"{', '.join(sorted(entry.value)) or 'no component'}"
        )
    return lines


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
"""One line per step type (`stages.STAGES` id) saying what it fits."""


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
