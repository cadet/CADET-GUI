"""Live "before you run" checks of one characterization step. Headless (no ipywidgets).

`step_checks` evaluates a step against its study: measurements and replicates,
injection markers, measurement problems (including baseline and normalization
errors found by building the reference), requirements from earlier steps, species
gaps, values the experiment types assume, and the known hardware values the chain
guide names. Each open item carries `CheckAction`s: a navigation target of the
characterization workbench (`"measurements"`, `"step"`, `"system"`, `"parameters"`)
with its context, or a step-local action (`TRANSFER`, `RECORD_ASSUMPTIONS`,
`CONFIRM_KNOWN`). A hardware value left at its default is a note, not a blocker:
`confirm_known_value` records it (or a corrected value) as known hardware.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Collection, Dict, List, Mapping, Optional, Sequence, Tuple

from .cadetprocessadapter import UNIT_LABELS
from .characterization_guide import (
    EXPERIMENT_TYPES,
    ChainStepGuide,
    guide_for_step,
    missing_assumptions,
    parameter_label,
    parameter_unit,
    record_assumptions,
    species_gap_messages,
)
from .characterization_runner import StepSetup, species_gaps
from .comparison import Comparison
from .parameter_store import (
    ParameterSpec,
    ParameterStore,
    Provenance,
    Step,
    missing_requirements,
    read_process,
    spec_for,
)
from .process_builder import build_process, check_recipe, recipe_key

__all__ = [
    "TRANSFER",
    "RECORD_ASSUMPTIONS",
    "CONFIRM_KNOWN",
    "CONFIRMED_DEFAULT",
    "KNOWN_HARDWARE",
    "CheckAction",
    "StepCheck",
    "step_checks",
    "StepStatus",
    "study_steps_status",
    "reference_problem",
    "known_value_source",
    "known_value_label",
    "quantity_text",
    "confirm_known_value",
]

TRANSFER = "transfer"
RECORD_ASSUMPTIONS = "record_assumptions"
CONFIRM_KNOWN = "confirm_known"
CONFIRMED_DEFAULT = "confirmed default"
KNOWN_HARDWARE = "known hardware"
_MARKER_PROBLEM = "No run-log marker starts with"


@dataclass(frozen=True)
class CheckAction:
    """A fix for an open check: a navigation `target` with `context`, or a local action."""

    label: str
    target: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepCheck:
    """One live check; `status` is "ok", "warn" or "info"."""

    id: str
    status: str
    text: str
    actions: Tuple[CheckAction, ...] = ()


def _open(comparison: Comparison) -> CheckAction:
    return CheckAction(
        f"Open {comparison.name}", "measurements", {"select": comparison.name}
    )


_REFERENCE_CACHE_SIZE = 64
_reference_cache: "OrderedDict[tuple, Optional[str]]" = OrderedDict()


def reference_problem(comparison: Comparison) -> Optional[str]:
    """Return why the measured trace cannot be prepared (alignment, baseline, scaling), or None.

    Builds the reference the fit would compare against; memoized by the comparison's
    content and loaded run.
    """
    if comparison.run is None:
        return None
    key = (
        json.dumps(comparison.to_dict(), sort_keys=True, default=str),
        recipe_key(comparison.recipe, comparison.overrides),
        id(comparison.run),
    )
    if key in _reference_cache:
        _reference_cache.move_to_end(key)
        return _reference_cache[key]
    try:
        process = build_process(comparison.recipe, overrides=comparison.overrides)
        reference = comparison.build_reference(process)
        problem = None if len(reference.time) else (
            "No measured points fall inside the simulated run after alignment."
        )
    except Exception as exc:  # noqa: BLE001 -- reported as the check's text
        problem = str(exc)
    _reference_cache[key] = problem
    while len(_reference_cache) > _REFERENCE_CACHE_SIZE:
        _reference_cache.popitem(last=False)
    return problem


def known_value_source(
    store: ParameterStore, comparisons: Sequence[Comparison], path: str
) -> Optional[str]:
    """Return where a known value of `path` comes from, or None if nothing sets it.

    "the parameter store" when the store holds it, "the system setup" when every
    recipe that carries `path` sets it explicitly (unit, column or binding values).
    """
    if path in store:
        return "the parameter store"
    parts = path.split(".")
    if len(parts) < 3 or parts[0] != "flow_sheet":
        return None
    unit, name = parts[1], parts[-1]
    for comparison in comparisons:
        recipe = comparison.recipe
        if unit == "column" and parts[2] == "binding_model":
            values = recipe.binding_values
        elif unit == "column":
            values = recipe.column_values
        else:
            instrument = recipe.instrument
            values = instrument.unit_values.get(unit, {}) if instrument is not None else {}
        if name not in {**values, **comparison.overrides}:
            return None
    return "the system setup"


def _measurement_checks(
    setup: StepSetup, guide: Optional[ChainStepGuide]
) -> List[StepCheck]:
    step_context = {"step_id": guide.id} if guide is not None else {}
    add = CheckAction("Add measurement for this step", "measurements", step_context)
    n = len(setup.comparisons)
    checks = []
    if n == 0:
        checks.append(StepCheck("measurements", "warn", "No measurements attached.", (add,)))
    elif n == 1:
        checks.append(StepCheck(
            "measurements", "info",
            "1 measurement attached. A replicate run lets an outlier show up.",
            (CheckAction("Add a replicate", "measurements", step_context),),
        ))
    else:
        checks.append(StepCheck(
            "measurements", "ok", f"{n} measurements attached (replicates)."
        ))
    if guide is not None and n:
        attached = {c.experiment_type for c in setup.comparisons}
        for type_id in guide.experiment_types:
            if type_id not in attached:
                label = EXPERIMENT_TYPES[type_id].label
                checks.append(StepCheck(
                    f"type:{type_id}", "warn", f"No {label} measurement attached.",
                    (CheckAction(
                        f"Add {label}", "measurements",
                        {**step_context, "experiment_type": type_id},
                    ),),
                ))
    return checks


def _marker_checks(setup: StepSetup) -> List[StepCheck]:
    checks, loaded = [], [c for c in setup.comparisons if c.run is not None]
    for comparison in loaded:
        if comparison.injection_marker is None and comparison.measured_injection is None:
            checks.append(StepCheck(
                f"marker:{comparison.name}", "warn",
                f"{comparison.name}: no injection marker picked; the measured clock is "
                "taken as the simulated one.", (_open(comparison),),
            ))
            continue
        try:
            comparison.measured_injection_x()
        except ValueError:
            checks.append(StepCheck(
                f"marker:{comparison.name}", "warn",
                f"{comparison.name}: injection marker {comparison.injection_marker!r} not "
                "found in the run log.", (_open(comparison),),
            ))
    if loaded and not checks:
        checks.append(StepCheck(
            "markers", "ok", f"Injection marker found in every measurement ({len(loaded)})."
        ))
    return checks


def _problem_checks(
    study: Any, setup: StepSetup, unaligned: Sequence[str]
) -> List[StepCheck]:
    checks = []
    for comparison in setup.comparisons:
        problems = [
            p for p in study.measurement_problems(comparison) if not p.startswith(_MARKER_PROBLEM)
        ]
        if not problems and comparison.name not in unaligned:
            reference = reference_problem(comparison)
            problems = [reference] if reference is not None else []
        if problems:
            checks.append(StepCheck(
                f"problems:{comparison.name}", "warn",
                f"{comparison.name}: " + " ".join(problems), (_open(comparison),),
            ))
    if setup.comparisons and not checks:
        checks.append(StepCheck(
            "problems", "ok",
            f"Every measured curve is ready to fit ({len(setup.comparisons)}): file read, "
            "detector signal found, baseline and scaling applied.",
        ))
    return checks


def _requirement_checks(
    study: Any, setup: StepSetup, guide: Optional[ChainStepGuide], prior: ParameterStore
) -> List[StepCheck]:
    requires = tuple(dict.fromkeys((*setup.requires, *(guide.requires if guide else ()))))
    if not requires:
        return []
    missing = missing_requirements(Step(setup.name, requires=requires), prior)
    if not missing:
        return [StepCheck(
            "requires", "ok",
            "Values from earlier steps are in the store: "
            + ", ".join(parameter_label(p) for p in requires) + ".",
        )]
    names = [s.name for s in study.steps]
    earlier = study.steps[: names.index(setup.name)] if setup.name in names else study.steps
    by_provider: Dict[Optional[str], List[str]] = {}
    for path in missing:
        provider = None
        for step in earlier:
            try:
                provides = step.provides
            except ValueError:
                continue
            if path in provides:
                provider = step.name
        by_provider.setdefault(provider, []).append(path)
    checks = []
    for provider, paths in by_provider.items():
        labels = ", ".join(parameter_label(p) for p in paths)
        if provider is not None:
            checks.append(StepCheck(
                f"requires:{provider}", "warn",
                f"Needs {labels}; accept {provider} first.",
                (CheckAction(f"Open {provider}", "step", {"name": provider}),),
            ))
        else:
            checks.append(StepCheck(
                "requires:store", "warn",
                f"Needs {labels}; no earlier step provides it. Add a known value to the "
                "parameter store or add the step that fits it.",
                (CheckAction("Open parameters", "parameters"),),
            ))
    return checks


def _species_checks(
    study: Any, setup: StepSetup, prior: ParameterStore
) -> List[StepCheck]:
    assumed = record_assumptions(setup, prior)
    try:
        gaps = species_gaps(setup, assumed)
    except Exception:  # noqa: BLE001 -- an unbuildable recipe is a measurement problem
        return []
    if not gaps:
        return []
    lines = species_gap_messages(study, setup, gaps, assumed)
    return [StepCheck(
        "species_gaps", "warn",
        "Stored values lack this step's components: " + ". ".join(lines)
        + ". Carry them over explicitly.",
        (CheckAction("Transfer to this step's species", TRANSFER, {"gaps": gaps}),),
    )]


def _assumption_checks(setup: StepSetup, prior: ParameterStore) -> List[StepCheck]:
    missing = missing_assumptions(setup, prior)
    if not missing:
        return []
    items = list(dict.fromkeys(
        f"{parameter_label(path)} = {value:g} for {comparison.probe} "
        f"({EXPERIMENT_TYPES[comparison.experiment_type].label})"
        for comparison, path, value in missing
    ))
    return [StepCheck(
        "assumptions", "warn",
        "The experiment types assume values the parameter store does not hold: "
        + "; ".join(items) + ".",
        (CheckAction("Record the assumptions", RECORD_ASSUMPTIONS),),
    )]


_UNIT_NOUNS: Dict[str, str] = {
    "tubing_pre_injection": "Pre-injection tubing",
    "tubing_pre_column": "Pre-column tubing",
    "tubing_post_column": "Post-column tubing",
    "tubing_detectors": "Detector tubing",
}
_NAMED_PATHS: Dict[str, str] = {
    "flow_sheet.column.particle_radius": "Particle radius",
    "flow_sheet.column.binding_model.capacity": "Ionic capacity",
}
_LENGTH_SCALES = ((1.0, 1.0, "m"), (1e-4, 1e-3, "mm"), (0.0, 1e-6, "µm"))
"""(smallest value, scale, unit) for showing a length."""


def known_value_label(path: str) -> str:
    """Return a lab label for a hardware path, e.g. "Pre-column tubing diameter"."""
    if path in _NAMED_PATHS:
        return _NAMED_PATHS[path]
    parts = path.split(".")
    if len(parts) < 3 or parts[0] != "flow_sheet":
        return parameter_label(path)
    noun = _UNIT_NOUNS.get(parts[1], UNIT_LABELS.get(parts[1], parts[1]))
    return f"{noun} {parts[-1].replace('_', ' ')}"


def _plain_unit(latex: str) -> str:
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", latex or "")
    text = text.replace("^{3}", "³").replace("^{2}", "²").replace("^{-1}", "⁻¹")
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", text)
    return text.replace("\\cdot", "·").replace("{", "").replace("}", "").replace("\\", "")


def quantity_text(value: float, latex_unit: str) -> Tuple[str, float, str]:
    """Return `value` as readable text plus the display `(scale, unit)`, lengths in mm or µm."""
    unit = _plain_unit(latex_unit)
    scale = 1.0
    if unit == "m" and value:
        scale, unit = next((f, u) for low, f, u in _LENGTH_SCALES if abs(value) >= low)
    text = f"{value / scale:.4g}"
    return (f"{text} {unit}" if unit else text), scale, unit


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value.item() if hasattr(value, "item") and getattr(value, "size", 0) == 1 else value


def _process_value(comparison: Comparison, path: str) -> Tuple[Optional[float], str]:
    """Return the value `comparison`'s built process uses for `path` and its LaTeX unit."""
    check = check_recipe(comparison.recipe, comparison.overrides)
    process = check.process
    try:
        reader = ParameterStore(specs={path: spec_for(process, path)})
        value = _scalar(read_process(process, [path], reader)[path])
    except KeyError:
        return None, ""
    if not isinstance(value, (int, float)):
        return None, ""
    return float(value), parameter_unit(process, path)


def confirm_known_value(
    study: Any, path: str, value: float, note: str = CONFIRMED_DEFAULT
) -> ParameterStore:
    """Record `value` of hardware `path` as known in the initial store; return that store.

    Accepted posteriors that lack `path` get the same entry, so every step's prior
    holds it, as if it had been recorded before the first step.
    """
    provenance = Provenance(step="initial", source=KNOWN_HARDWARE, note=note)
    spec = {path: ParameterSpec(path=path)}

    def record(store: ParameterStore) -> ParameterStore:
        updated = store.updated({path: float(value)}, provenance, specs=spec)
        return replace(updated, step=store.step, prior=store.prior)

    study.initial_store = record(study.initial_store)
    for name, posterior in list(study.posteriors.items()):
        if path not in posterior:
            study.posteriors[name] = record(posterior)
    study.notify()
    return study.initial_store


def _known_value_checks(
    setup: StepSetup, guide: Optional[ChainStepGuide], prior: ParameterStore
) -> List[StepCheck]:
    if guide is None:
        return []
    checks = []
    for path in guide.known_values:
        carriers = []
        for comparison in setup.comparisons:
            check = check_recipe(comparison.recipe, comparison.overrides)
            if check.error is None and check.has_parameter(path):
                carriers.append(comparison)
        if not carriers:
            continue
        source = known_value_source(prior, carriers, path)
        label = known_value_label(path)
        value, unit = _process_value(carriers[0], path)
        if source == "the parameter store":
            entry = prior.entries[path]
            stored = _scalar(entry.value)
            if isinstance(stored, (int, float)):
                value = float(stored)
            if entry.provenance.note == CONFIRMED_DEFAULT:
                source = "confirmed default, in the parameter store"
            else:
                source = "in the parameter store"
        elif source is not None:
            source = "set in the system setup"
        shown = quantity_text(value, unit) if value is not None else None
        if source is None and shown is None:
            checks.append(StepCheck(
                f"known:{path}", "info",
                f"{label}: using the default value. Is that your hardware?",
                (CheckAction("Edit in System", "system", {"unit": path.split(".")[1]}),),
            ))
        elif source is None:
            text, scale, display_unit = shown
            checks.append(StepCheck(
                f"known:{path}", "info",
                f"{label}: using the default {text}. Is that your hardware?",
                (
                    CheckAction("Use this value", CONFIRM_KNOWN, {
                        "path": path, "value": value, "scale": scale, "unit": display_unit,
                    }),
                    CheckAction("Edit in System", "system", {"unit": path.split(".")[1]}),
                ),
            ))
        else:
            value_text = f" {shown[0]}" if shown is not None else ""
            checks.append(StepCheck(
                f"known:{path}", "ok", f"{label}:{value_text} ({source}).",
            ))
    return checks


def step_checks(study: Any, setup: StepSetup) -> List[StepCheck]:
    """Return the live pre-run checks of `setup` in `study`, open items with their fixes."""
    guide = guide_for_step(setup)
    names = [s.name for s in study.steps]
    prior = study.prior_for(setup.name) if setup.name in names else study.current_store
    checks = _measurement_checks(setup, guide)
    markers = _marker_checks(setup)
    unaligned = [c.id.partition(":")[2] for c in markers if c.status == "warn"]
    checks += markers
    checks += _problem_checks(study, setup, unaligned)
    checks += _requirement_checks(study, setup, guide, prior)
    if setup.comparisons and not any(
        c.status == "warn" and c.id.startswith("problems:") for c in checks
    ):
        checks += _assumption_checks(setup, prior)
        checks += _species_checks(study, setup, prior)
    checks += _known_value_checks(setup, guide, prior)
    return checks


@dataclass(frozen=True)
class StepStatus:
    """Where one study step stands, for the Setup pane.

    `measurements` maps experiment type id (or "untagged") to comparison names;
    `problems` are the texts of the open (warn) `checks`.
    """

    step_name: str
    guide: Optional[ChainStepGuide]
    measurements: Dict[str, List[str]]
    checks: Tuple[StepCheck, ...]
    fitted: bool
    accepted: bool
    next_action: str

    @property
    def open_checks(self) -> List[StepCheck]:
        """The checks that still need attention."""
        return [c for c in self.checks if c.status == "warn"]

    @property
    def problems(self) -> List[str]:
        """The texts of the open checks."""
        return [c.text for c in self.open_checks]

    @property
    def ready(self) -> bool:
        """Whether no check needs attention."""
        return not self.open_checks

    @property
    def species_gaps(self) -> Dict[str, List[str]]:
        """Stored values that lack this step's species, by path."""
        for check in self.open_checks:
            for action in check.actions:
                if action.target == TRANSFER:
                    return dict(action.context["gaps"])
        return {}


def _step_title(step: StepSetup) -> str:
    guide = guide_for_step(step)
    return guide.title if guide is not None else step.name


def _next_action(
    study: Any, position: int, open_checks: Sequence[StepCheck], fitted: bool, accepted: bool
) -> str:
    if accepted:
        later = study.steps[position + 1:]
        return (
            f"Accepted. Continue with {_step_title(later[0])}." if later
            else "Accepted. The chain is complete."
        )
    if open_checks:
        return open_checks[0].text
    return "Choose a Pareto candidate and accept it." if fitted else "Run the fit."


def study_steps_status(study: Any, fitted: Collection[str] = ()) -> List[StepStatus]:
    """Return one `StepStatus` per step of `study`, in chain order, from `step_checks`.

    `fitted` names the steps that have a fit result waiting for a choice (results are
    not part of the study).
    """
    statuses = []
    for position, step in enumerate(study.steps):
        measurements: Dict[str, List[str]] = {}
        for comparison in step.comparisons:
            key = comparison.experiment_type or "untagged"
            measurements.setdefault(key, []).append(comparison.name)
        checks = tuple(step_checks(study, step))
        accepted = step.name in study.posteriors
        is_fitted = step.name in fitted
        open_checks = [c for c in checks if c.status == "warn"]
        statuses.append(StepStatus(
            step_name=step.name,
            guide=guide_for_step(step),
            measurements=measurements,
            checks=checks,
            fitted=is_fitted,
            accepted=accepted,
            next_action=_next_action(study, position, open_checks, is_fitted, accepted),
        ))
    return statuses
