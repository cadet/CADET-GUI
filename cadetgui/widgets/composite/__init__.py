# =========================================
# File: cadetgui/widgets/composite/__init__.py
# =========================================
"""Task widgets assembled from elements + forms.

See ai-docs/ARCHITECTURE.md's "Composition, not inheritance-of-everything" note.
"""
from .configuration import ConfigurationWidget
from .solution import SolutionWidget

__all__ = ["ConfigurationWidget", "SolutionWidget"]
