from __future__ import annotations

import ast
import math
import re
from html import escape
from typing import Any, List, Optional

import numpy as np
from CADETProcess.dataStructure.parameter import NdPolynomial, Polynomial
from CADETProcess.processModel import NoBinding

__all__ = [
    "components_html",
    "parameter_names",
    "parameter_owners",
    "format_value",
    "value_html",
    "assign_literal",
]


def components_html(component_system: Any) -> str:
    """One line naming the components of a ComponentSystem."""
    names = ", ".join(escape(name) for name in component_system.names)
    return f"<div class='cadetgui-note'>Components: {names}</div>"


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


def _value(obj: Any, name: str) -> Any:
    value = getattr(obj, name)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    # Polynomial inputs (e.g. Inlet.c) hold [constant, linear, quadratic, cubic] per entry;
    # while the profile is constant, only the constants matter.
    if value is not None and isinstance(getattr(type(obj), name, None), (NdPolynomial, Polynomial)):
        rows = value if value and isinstance(value[0], list) else [value]
        if all(not any(row[1:]) for row in rows):
            constants = [row[0] for row in rows]
            value = constants if isinstance(value[0], list) else constants[0]
    # Per-component values that agree for all components read as one value.
    if isinstance(value, list) and value and not isinstance(value[0], list):
        if all(v == value[0] for v in value):
            value = value[0]
    return value


def _number_text(x: Any) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return repr(x)
    return re.sub(r"e\+?(-?)0*(\d)", r"e\1\2", f"{x:g}")


def format_value(obj: Any, name: str) -> str:
    """Format parameter `name` of `obj` for editing, e.g. `1e-7` or `1, 2`; "" if unset."""
    value = _value(obj, name)
    if value is None:
        return ""
    if isinstance(value, list) and not any(isinstance(v, list) for v in value):
        return ", ".join(_number_text(v) for v in value)
    if isinstance(value, list):
        return repr(value)
    return _number_text(value)


def _number_html(x: Any) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return escape(str(x))
    if x == 0 or 1e-3 <= abs(x) < 1e4:
        return _number_text(x)
    exponent = math.floor(math.log10(abs(x)))
    mantissa = _number_text(round(x / 10**exponent, 6))
    power = f"10<sup>{exponent}</sup>".replace("-", "−")
    return power if mantissa == "1" else f"{mantissa} × {power}"


def value_html(obj: Any, name: str) -> Optional[str]:
    """Render parameter `name` of `obj` for reading, per component if values differ."""
    value = _value(obj, name)
    if value is None:
        return None
    if not isinstance(value, list):
        return _number_html(value)
    if any(isinstance(v, list) for v in value):
        return escape(repr(value))
    names = list(getattr(getattr(obj, "component_system", None), "names", []))
    if len(names) != len(value):
        return ", ".join(_number_html(v) for v in value)
    return ", ".join(f"{escape(n)}: {_number_html(v)}" for n, v in zip(names, value))


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
