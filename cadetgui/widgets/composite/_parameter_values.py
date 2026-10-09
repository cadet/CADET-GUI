from __future__ import annotations

import ast
from typing import Any, List, Optional

import numpy as np
from CADETProcess.dataStructure.parameter import NdPolynomial, Polynomial
from CADETProcess.processModel import NoBinding

__all__ = ["parameter_names", "parameter_owners", "format_value", "assign_literal"]


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


def format_value(obj: Any, name: str) -> str:
    """Format parameter `name` of `obj` as a Python literal, "" if unset."""
    value = getattr(obj, name)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if value is None:
        return ""
    # Polynomial inputs (e.g. Inlet.c) hold [constant, linear, quadratic, cubic] per entry;
    # show only the constants while the profile is constant.
    if isinstance(getattr(type(obj), name, None), (NdPolynomial, Polynomial)):
        rows = value if value and isinstance(value[0], list) else [value]
        if all(not any(row[1:]) for row in rows):
            constants = [row[0] for row in rows]
            value = constants if isinstance(value[0], list) else constants[0]
    return repr(value)


def assign_literal(obj: Any, name: str, text: str) -> Optional[str]:
    """Assign the Python literal `text` to parameter `name` of `obj`; return an error or None."""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return "Enter a number or a list, e.g. 0.4 or [1, 2]."
    try:
        setattr(obj, name, value)
    except (ValueError, TypeError) as exc:
        return str(exc)
    return None
