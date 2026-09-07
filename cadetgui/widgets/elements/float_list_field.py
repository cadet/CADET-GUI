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
    """List of floats.

    Two modes:

    - **Pinned** (`component_names` given, non-empty): exactly one row per
      name, no add/remove -- the row count is controlled externally (by the
      component system), not by the user. Each row is labeled with its
      component's name once there's more than one (a single component has
      nothing to disambiguate).
    - **Free-form** (`component_names` omitted/empty): the original
      add/remove row editor, for values with no natural per-component
      correspondence.
    """

    value = T.List(T.Float()).tag(sync=True)
    component_names = T.List(T.Unicode()).tag(sync=True)

    _esm = _DIR / "float_list_field.js"
    _css = _DIR / "_shared.css"

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
            # pinned mode: row count must exactly match the component count,
            # regardless of what `value` happened to contain.
            values = (values + [0.0] * len(names))[: len(names)]
        super().__init__(
            label=label, value=values, units=units or "", component_names=names,
            validate=validate,
        )
