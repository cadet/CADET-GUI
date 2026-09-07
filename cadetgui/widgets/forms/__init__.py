# =========================================
# File: cadetgui/widgets/forms/__init__.py
# =========================================
"""Renders a ModelSpec into a form of anywidget Elements.

See ai-docs/ARCHITECTURE.md's data-flow section for where this fits.
"""
from .renderer import FormRenderer, element_for_field

__all__ = ["FormRenderer", "element_for_field"]
