"""Parameter values of CADET-Process objects as HTML."""

from __future__ import annotations

from html import escape
from typing import Any, Optional

from ...process_model.values import plain_value
from ..ui.format import number_html

__all__ = ["components_html", "value_html"]


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
