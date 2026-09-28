from __future__ import annotations

from typing import List, Optional, Sequence

import traitlets as T

from ._assets import FIELD_CSS, field_esm
from .base import Element, Validator

__all__ = ["FloatListField"]


class FloatListField(Element):
    """List of floats.

    With `component_names` the list is pinned: one row per name, no add/remove, and
    `value` is padded or truncated to match. Without them rows can be added and removed.
    """

    value = T.List(T.Float()).tag(sync=True)
    component_names = T.List(T.Unicode()).tag(sync=True)

    _esm = field_esm("float_list_field")
    _css = FIELD_CSS

    def __init__(
        self,
        *,
        label: str = "",
        value: Optional[Sequence[float]] = None,
        units: Optional[str] = None,
        component_names: Optional[Sequence[str]] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        names: List[str] = list(component_names) if component_names else []
        values: List[float] = [float(v) for v in value] if value else [0.0]
        if names:
            values = (values + [0.0] * len(names))[: len(names)]
        super().__init__(
            label=label, value=values, units=units or "", component_names=names,
            validate=validate,
        )
