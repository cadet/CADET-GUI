"""Shared standard starting values for model parameters and methods. Headless.

`parameters/starting_values.json` lists, per binding model, `scalar` and `per_component`
values and, under `methods`, per process template the method values that suit it;
with `salt_first` the first component is the salt. Binding values only fill parameters
that are missing or zero; method values replace the template's defaults, and the column
then starts equilibrated with the method's starting salt.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .configuration_store import ConfigurationState

__all__ = [
    "starting_values",
    "binding_starting_values",
    "method_starting_values",
    "with_starting_values",
]

_PATH = Path(__file__).parent / "parameters" / "starting_values.json"


@lru_cache(maxsize=1)
def starting_values() -> Dict[str, Any]:
    """Return the parsed `starting_values.json`."""
    return json.loads(_PATH.read_text(encoding="utf-8"))


def _entry(binding_key: str) -> Optional[Dict[str, Any]]:
    return starting_values()["binding"].get(binding_key)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_unset(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return all(_is_number(v) and v == 0 for v in value)
    return value is None or (_is_number(value) and value == 0)


def binding_starting_values(
    binding_key: str, components: Sequence[str], values: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return `values` with the binding parameters that are missing or zero filled in.

    Switches such as `is_kinetic` are only set when no numeric binding value is set yet.
    """
    start = _entry(binding_key)
    out = dict(values)
    if start is None:
        return out
    untouched = all(_is_unset(v) for v in values.values() if not isinstance(v, bool))
    for key, value in start.get("scalar", {}).items():
        if key not in out or (untouched if isinstance(value, bool) else _is_unset(out[key])):
            out[key] = value
    salt = 0 if start.get("salt_first") else None
    for key, value in start.get("per_component", {}).items():
        current = out.get(key)
        if not isinstance(current, (list, tuple)) or len(current) != len(components):
            current = [0.0] * len(components)
        out[key] = [
            0.0 if i == salt else (c if not _is_unset(c) else value)
            for i, c in enumerate(current)
        ]
    return out


def method_starting_values(
    binding_key: str, template_key: str, components: Sequence[str], values: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """Return `values` with the method values listed for `template_key`, or None if none are."""
    start = _entry(binding_key)
    method = (start or {}).get("methods", {}).get(template_key)
    if method is None:
        return None
    out = dict(values)
    for key, value in method.items():
        if key == "note":
            continue
        if isinstance(value, dict):
            out[key] = [value["salt"]] + [value["other"]] * (len(components) - 1)
        else:
            out[key] = value
    return out


def _initial_salt(model_values: Mapping[str, Any]) -> float:
    for key in ("c_buffer_a", "c_sample"):
        values = model_values.get(key)
        if isinstance(values, (list, tuple)) and values:
            return float(values[0])
    return 0.0


def with_starting_values(
    recipe: ConfigurationState, *, method: bool = True, equilibrate: bool = True
) -> ConfigurationState:
    """Return `recipe` with binding starting values and, if `method`, its method values.

    With a salt-first binding model and `equilibrate` the column starts equilibrated:
    `c` and `cp` (ignored by models without pores) hold the starting salt (buffer A, else
    the sample) and `q` the capacity, for the salt only. Method values reset that state;
    without them it is only set while `c`, `cp` and `q` are unset. A salt-first model
    with real values stalls the solver on any other start.
    """
    start = _entry(recipe.binding_key)
    if start is None:
        return recipe
    binding = binding_starting_values(
        recipe.binding_key, recipe.components, recipe.binding_values
    )
    model = (
        method_starting_values(
            recipe.binding_key, recipe.template_key, recipe.components, recipe.model_values
        ) if method else None
    )
    column = dict(recipe.column_values)
    show_optional = recipe.show_optional_column
    unset = all(_is_unset(column.get(k)) for k in ("c", "cp", "q"))
    if equilibrate and start.get("salt_first") and (model is not None or unset):
        rest = [0.0] * (len(recipe.components) - 1)
        salt = _initial_salt(model if model is not None else recipe.model_values)
        column["c"] = column["cp"] = [salt, *rest]
        column["q"] = [float(binding.get("capacity", 0.0)), *rest]
        show_optional = True
    return replace(
        recipe,
        binding_values=binding,
        model_values=model if model is not None else recipe.model_values,
        column_values=column,
        show_optional_column=show_optional,
    )
