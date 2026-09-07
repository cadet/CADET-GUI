# =========================================
# File: cadetgui/widgets/legacy/__init__.py
# =========================================
"""ipywidgets-based prototype — reference material for the anywidget port.

Not the target implementation (see ai-docs/ARCHITECTURE.md). Kept working and
importable so the existing notebook keeps functioning during the port.
"""
from .base import BaseWidget, ListenerMixin
from .config import ConfigurationWidget
from .elements import (
    BoolField,
    ChoiceField,
    Display,
    Element,
    FloatField,
    ObjectChoiceField,
    Popup,
    TextField,
)
from .form import FormRenderer
from .solution import SolutionWidget

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
