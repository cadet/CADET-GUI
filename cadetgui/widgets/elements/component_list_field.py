from __future__ import annotations

from typing import List, Optional, Sequence

import traitlets as T

from .assets import FIELD_CSS, field_esm
from .base import Element, Validator

__all__ = ["ComponentListField"]


class ComponentListField(Element):
    """Editable list of component names; defaults to one ("Component 1").

    The remove buttons are disabled once the row count reaches `min_components`. With
    `blank_rows`, the list may be empty and added rows start without a name.
    """

    value = T.List(T.Unicode()).tag(sync=True)
    min_components = T.Int(1).tag(sync=True)
    blank_rows = T.Bool(False).tag(sync=True)

    _esm = field_esm("component_list_field", units=False)
    _css = FIELD_CSS

    def __init__(
        self,
        *,
        label: str = "",
        value: Optional[Sequence[str]] = None,
        validate: Optional[Validator] = None,
        blank_rows: bool = False,
    ) -> None:
        names: List[str] = list(value or []) if value or blank_rows else ["Component 1"]
        super().__init__(
            label=label,
            value=names,
            validate=validate,
            blank_rows=blank_rows,
            min_components=0 if blank_rows else 1,
        )
