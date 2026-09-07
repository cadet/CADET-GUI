# =========================================
# File: cadetgui/widgets/__init__.py
# =========================================
"""Composable widgets for CADET-GUI.

This subpackage provides:
- elements: atomic anywidget input controls (the target implementation)
- legacy: the earlier ipywidgets-based prototype, kept working as reference
  material during the anywidget port (see ai-docs/ARCHITECTURE.md)

Public API re-exports the legacy prototype for now, since it's what's usable
end-to-end. Update this as anywidget equivalents land.
"""
from .legacy import (
    BaseWidget,
    BoolField,
    ChoiceField,
    ConfigurationWidget,
    Display,
    Element,
    FloatField,
    FormRenderer,
    ListenerMixin,
    ObjectChoiceField,
    Popup,
    SolutionWidget,
    TextField,
)

__all__ = [
    "BaseWidget",
    "ListenerMixin",
    "Element",
    "TextField",
    "FloatField",
    "BoolField",
    "Display",
    "Popup",
    "ChoiceField",
    "ObjectChoiceField",
    "FormRenderer",
    "ConfigurationWidget",
    "SolutionWidget",
]
