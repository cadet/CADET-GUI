# =========================================
# File: cadetgui/widgets/elements/float_list_field.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

import traitlets as T

from .base import Element, Validator

__all__ = ["FloatListField"]

_DIR = Path(__file__).parent


class FloatListField(Element):
    """Editable list of floats with add/remove rows."""

    value = T.List(T.Float()).tag(sync=True)

    _esm = _DIR / "float_list_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        value: Optional[Sequence[float]] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        values: List[float] = [float(v) for v in value] if value else [0.0]
        super().__init__(label=label, value=values, validate=validate)
