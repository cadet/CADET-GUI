"""Loader for the parameter metadata ground truth (`interface.json`).

Framework-agnostic (no widget/CADET-Process imports) -- see
ai-docs/ARCHITECTURE.md's "Parameter metadata schema" for the design and
ai-docs/REQUIREMENTS.md item #5 for why this exists as one file rather than
scattered per-widget constants.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["load_schema", "get_parameters", "get_parameter", "required_parameters"]

_SCHEMA_PATH = Path(__file__).parent / "interface.json"


def _resolve_refs(node: Any, root: dict) -> Any:
    """Recursively replace `{"$ref": "a.b.c"}` with the dotted-path value from `root`."""
    if isinstance(node, dict):
        if set(node.keys()) == {"$ref"}:
            target: Any = root
            for part in node["$ref"].split("."):
                target = target[part]
            return _resolve_refs(target, root)
        return {k: _resolve_refs(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, root) for v in node]
    return node


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Load and `$ref`-resolve `interface.json`. Cached -- the file doesn't change at runtime."""
    raw = json.loads(_SCHEMA_PATH.read_text())
    return _resolve_refs(raw, raw)


def get_parameters(category: str, model: str) -> dict[str, dict]:
    """All known parameters for `model` in `category`, keyed by CADET-Process name.

    Merges the category's `shared_parameters` (e.g. `length`, `diameter`,
    `axial_dispersion` -- identical across every TubularReactorBase-derived
    column) underneath the model's own_parameters, but only for models that
    opt in via `extends_shared_parameters: true` -- e.g. `Cstr` has a
    different base class and no column geometry, so it must not inherit them.
    """
    schema = load_schema()["categories"][category]
    model_entry = schema["models"][model]
    extends_shared = model_entry.get("extends_shared_parameters")
    shared = schema.get("shared_parameters", {}) if extends_shared else {}
    return {**shared, **model_entry["own_parameters"]}


def get_parameter(category: str, model: str, name: str) -> dict:
    """Metadata for one parameter, e.g. `get_parameter("binding", "Langmuir", "capacity")`."""
    return get_parameters(category, model)[name]


def required_parameters(category: str, model: str) -> list[str]:
    """Return the subset of `get_parameters(...)` CADET-Process requires to build `model`."""
    return load_schema()["categories"][category]["models"][model]["required_parameters"]
