# =========================================
# File: cadetgui/widgets/__init__.py
# =========================================
"""Composable ipywidgets for CADET-GUI.

This subpackage provides:
- elements: small form controls and simple display helpers
- base: BaseWidget and ListenerMixin
- form: FormRenderer to render a ModelSpec to a form
- config: ConfigurationWidget for model+column selection & config
- solution: SolutionWidget to run and visualize simulations

Public API is re-exported for convenience.
"""
from .elements import (
    Element,
    TextField,
    FloatField,
    BoolField,
    Display,
    Popup,
    ChoiceField,
    ObjectChoiceField
)
from .base import BaseWidget, ListenerMixin
from .form import FormRenderer
from .config import ConfigurationWidget
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
    "OverlayModal",
    "FormRenderer",
    "ConfigurationWidget",
    "SolutionWidget",
]



