from __future__ import annotations

from typing import Optional

import traitlets as T

from ._assets import FIELD_CSS, field_esm
from .base import Element, Validator

__all__ = ["TextField"]


class TextField(Element):
    """Single labeled text input."""

    value = T.Unicode("").tag(sync=True)

    _esm = field_esm("text_field")
    _css = FIELD_CSS

    def __init__(
        self,
        *,
        label: str = "",
        value: str = "",
        units: Optional[str] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        super().__init__(label=label, value=value, units=units or "", validate=validate)
