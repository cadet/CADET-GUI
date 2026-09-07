# =========================================
# File: cadetgui/widgets/elements/bool_field.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import Optional

import traitlets as T

from .base import Element, Validator

__all__ = ["BoolField"]

_DIR = Path(__file__).parent


class BoolField(Element):
    """Single labeled checkbox."""

    value = T.Bool(False).tag(sync=True)

    _esm = _DIR / "bool_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        value: bool = False,
        validate: Optional[Validator] = None,
    ) -> None:
        super().__init__(label=label, value=value, validate=validate)
