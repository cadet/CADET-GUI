"""Recipes (saved configurations) and the process templates they run."""

from __future__ import annotations

import copy
import dataclasses
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..io.configuration_store import ConfigurationState
from ..parameters.specs import FieldSpec
from .templates import (
    INSTRUMENT_TEMPLATES,
    STANDALONE_TEMPLATES,
    template_required_units,
)

__all__ = [
    "template_registry",
    "template_fields",
    "recipe_template_fields",
    "template_options",
    "recipe_flow_rate",
    "recipe_with_template",
]


def template_registry(recipe: ConfigurationState) -> Dict[str, Callable[..., Any]]:
    """Return the templates a recipe can run: instrument ones, or standalone without one."""
    return INSTRUMENT_TEMPLATES if recipe.instrument is not None else STANDALONE_TEMPLATES


def template_fields(
    template_key: str, components: Sequence[str], *, standalone: bool = False
) -> List[FieldSpec]:
    """Return a process template's form fields for `components`, without a flow sheet."""
    registry = STANDALONE_TEMPLATES if standalone else INSTRUMENT_TEMPLATES
    factory = registry.get(template_key)
    if factory is None:
        return []
    # The template factories only read `component_system.names` before `build` is called.
    stub = SimpleNamespace(component_system=SimpleNamespace(names=list(components)))
    return factory(stub).fields


def recipe_template_fields(recipe: ConfigurationState) -> List[FieldSpec]:
    """Return the recipe's process-template fields (the values `overrides` may replace)."""
    return template_fields(
        recipe.template_key, recipe.components, standalone=recipe.instrument is None
    )


def template_options(recipe: ConfigurationState) -> List[Tuple[str, str]]:
    """Return `(label, key)` template options; the recipe's own one even if unavailable."""
    options = [(key, key) for key in template_registry(recipe)]
    if recipe.template_key not in dict(options).values():
        options.append((f"{recipe.template_key} (not available)", recipe.template_key))
    return options


def recipe_flow_rate(recipe: ConfigurationState) -> Optional[float]:
    """Return the recipe's flow rate (m³/s), or None if its template has none set."""
    value = recipe.model_values.get("flow_rate", recipe.model_values.get("flow_rate_wash"))
    return float(value) if value is not None else None


def recipe_with_template(recipe: ConfigurationState, template_key: str) -> ConfigurationState:
    """Return `recipe` running process template `template_key` with its default method values.

    The flow rate is kept; the sample loop is put in the flow path if the template needs it.
    """
    factory = template_registry(recipe)[template_key]
    changed = dataclasses.replace(recipe, template_key=template_key)
    values = {f.name: copy.deepcopy(f.default) for f in recipe_template_fields(changed)}
    flow_rate = recipe_flow_rate(recipe)
    if flow_rate is not None:
        for key in ("flow_rate", "flow_rate_wash"):
            if key in values:
                values[key] = flow_rate
    instrument = recipe.instrument
    if instrument is not None and "sample_loop" in template_required_units(factory):
        instrument = dataclasses.replace(instrument, include_sample_loop=True)
    return dataclasses.replace(changed, model_values=values, instrument=instrument)
