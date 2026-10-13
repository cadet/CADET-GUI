"""Read and set the parameters of CADET-Process objects as plain values and text."""

from __future__ import annotations

import ast
import math
import re
from typing import Any, List, Optional

import numpy as np
from CADETProcess.dataStructure.parameter import NdPolynomial, Polynomial
from CADETProcess.processModel import NoBinding

__all__ = [
    "parameter_names",
    "parameter_owners",
    "plain_value",
    "number_text",
    "format_value",
    "code_literal",
    "set_by_path",
    "resolve_path",
    "has_parameter",
    "assign_literal",
]


def parameter_names(obj: Any) -> List[str]:
    """List the required parameters of `obj`, then its other non-structured ones, each sorted."""
    required = sorted(getattr(obj, "required_parameters", []))
    others = sorted(
        name for name, value in obj.parameters.items()
        if name not in required and not isinstance(value, dict)
    )
    return required + others


def parameter_owners(process: Any) -> List[tuple[str, Any]]:
    """`(path prefix, object)` for every object below a process that holds parameters."""
    owners = []
    for unit in process.flow_sheet.units:
        prefix = f"flow_sheet.{unit.name}"
        owners.append((prefix, unit))
        binding_model = getattr(unit, "binding_model", None)
        if binding_model is not None and not isinstance(binding_model, NoBinding):
            owners.append((f"{prefix}.binding_model", binding_model))
    return owners


def plain_value(obj: Any, name: str) -> Any:
    """Return parameter `name` of `obj` as plain Python, in its shortest equivalent form.

    Constant polynomial inputs (e.g. `Inlet.c`) give their constants, and per-component
    values that agree for all components give one value; unset or empty gives None.
    """
    value = getattr(obj, name)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, list) and not value:
        return None
    # Polynomial inputs hold [constant, linear, quadratic, cubic] per entry.
    if value is not None and isinstance(getattr(type(obj), name, None), (NdPolynomial, Polynomial)):
        rows = value if value and isinstance(value[0], list) else [value]
        if all(not any(row[1:]) for row in rows):
            constants = [row[0] for row in rows]
            value = constants if isinstance(value[0], list) else constants[0]
    if isinstance(value, list) and value and not isinstance(value[0], list):
        if all(v == value[0] for v in value):
            value = value[0]
    return value


def number_text(x: Any, digits: Optional[int] = None) -> str:
    """Format a number compactly (`1e-7`, not `1e-07`); `digits` significant digits if given."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return repr(x)
    text = f"{x:.{digits}g}" if digits else f"{x:g}"
    return re.sub(r"e\+?(-?)0*(\d)", r"e\1\2", text)


def format_value(obj: Any, name: str) -> str:
    """Format parameter `name` of `obj` for editing, e.g. `1e-7` or `1, 2`; "" if unset."""
    value = plain_value(obj, name)
    if value is None or (isinstance(value, float) and math.isinf(value)):
        return ""
    if isinstance(value, list) and not any(isinstance(v, list) for v in value):
        return ", ".join(number_text(v) for v in value)
    if isinstance(value, list):
        return repr(value)
    return number_text(value)


def code_literal(obj: Any, name: str) -> str:
    """Format parameter `name` of `obj` as the right-hand side of a Python assignment."""
    value = plain_value(obj, name)
    if isinstance(value, list) and not any(isinstance(v, list) for v in value):
        return f"[{', '.join(number_text(v) for v in value)}]"
    if isinstance(value, list):
        return repr(value)
    return number_text(value)


def set_by_path(root: Any, path: str, value: Any) -> None:
    """Set the parameter at `path` below `root`, e.g. `flow_sheet.column.length`."""
    *owners, name = path.split(".")
    owner = root
    for part in owners:
        owner = getattr(owner, part)
    setattr(owner, name, value)


def assign_literal(obj: Any, name: str, text: str) -> Optional[str]:
    """Assign `text` (a number, or numbers separated by commas) to `obj.name`; return an error."""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return "Enter a number, or one number per component separated by commas."
    if isinstance(value, tuple):
        value = list(value)
    try:
        setattr(obj, name, value)
    except (ValueError, TypeError) as exc:
        return str(exc)
    return None


def has_parameter(process: Any, path: str) -> bool:
    """Return whether `process` carries the parameter at `path` (bypassed units don't)."""
    target, _, attribute = path.rpartition(".")
    obj = resolve_path(process, target)
    return obj is not None and hasattr(obj, attribute)


def resolve_path(root: Any, path: str) -> Any:
    """Walk a dotted path from `root`; return `None` if any step is absent."""
    obj = root
    for part in path.split("."):
        if not part:
            continue
        try:
            obj = obj[part] if _is_indexable(obj, part) else getattr(obj, part)
        except (AttributeError, KeyError):
            return None
    return obj


def _is_indexable(obj: Any, key: str) -> bool:
    """Return whether `key` should be looked up by item rather than by attribute."""
    return hasattr(obj, "__getitem__") and not hasattr(obj, key)
