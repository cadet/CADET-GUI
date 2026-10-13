"""Parameter values of CADET-Process objects as HTML."""

from __future__ import annotations

from html import escape
from typing import Any, List, Optional, Tuple

from ...process_model.values import parameter_names, plain_value
from ..ui.format import number_html

__all__ = ["components_html", "value_html", "parameter_groups", "MISSING_HTML"]

MISSING_HTML = "<span class='cadetgui-param-missing'>missing</span>"


def components_html(component_system: Any) -> str:
    """Return one line naming the components of a ComponentSystem."""
    names = ", ".join(escape(name) for name in component_system.names)
    return f"<div class='cadetgui-note'>Components: {names}</div>"


def value_html(obj: Any, name: str) -> Optional[str]:
    """Render parameter `name` of `obj` for reading, per component if values differ."""
    value = plain_value(obj, name)
    if value is None:
        return None
    if not isinstance(value, list):
        return number_html(value)
    if any(isinstance(v, list) for v in value):
        return escape(repr(value))
    names = list(getattr(getattr(obj, "component_system", None), "names", []))
    if len(names) != len(value):
        return ", ".join(number_html(v) for v in value)
    return ", ".join(f"{escape(n)}: {number_html(v)}" for n, v in zip(names, value))


def parameter_groups(obj: Any) -> List[Tuple[str, List[str]]]:
    """Split the parameters of `obj` into titled groups: required ones, then the others."""
    required = set(getattr(obj, "required_parameters", []))
    names = parameter_names(obj)
    groups = [
        ("Required parameters", [n for n in names if n in required]),
        ("Initial state and options" if required else "Parameters",
         [n for n in names if n not in required]),
    ]
    return [(title, group) for title, group in groups if group]
