from __future__ import annotations

from pathlib import Path
from typing import Optional

import traitlets as T

from .base import Element, Validator

__all__ = ["TextField"]

_DIR = Path(__file__).parent


class TextField(Element):
    """Single labeled text input."""

    value = T.Unicode("").tag(sync=True)

    _esm = _DIR / "text_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        value: str = "",
        units: Optional[str] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        super().__init__(label=label, value=value, units=units or "", validate=validate)
