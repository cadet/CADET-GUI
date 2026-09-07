# =========================================
# File: cadetgui/widgets/elements/float_field.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import Optional

import traitlets as T

from .base import Element, Validator

__all__ = ["FloatField"]

_DIR = Path(__file__).parent


class FloatField(Element):
    """Single labeled float input with optional min/max bounds."""

    value = T.Float(0.0).tag(sync=True)
    min = T.Float(allow_none=True, default_value=None).tag(sync=True)
    max = T.Float(allow_none=True, default_value=None).tag(sync=True)

    _esm = _DIR / "float_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        value: float = 0.0,
        min: Optional[float] = None,
        max: Optional[float] = None,
        units: Optional[str] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        super().__init__(
            label=label, value=value, min=min, max=max, units=units or "", validate=validate
        )
