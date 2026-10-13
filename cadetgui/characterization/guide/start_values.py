"""The values a step's fitted variables start from, with their units and sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from ...instrument.process_builder import check_recipe
from ...parameters import get_parameters
from ...process_model.values import has_parameter
from ..parameter_store import ParameterStore, read_process, spec_for
from ..runner import StepSetup
from ..stages import VariableDef, describe_stage
from .chain import step_title


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
    return f"from {step_title(setup) if setup is not None else step}"


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
