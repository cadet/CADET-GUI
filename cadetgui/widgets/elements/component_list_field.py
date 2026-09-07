# =========================================
# File: cadetgui/widgets/elements/component_list_field.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

import traitlets as T

from .base import Element, Validator

__all__ = ["ComponentListField"]

_DIR = Path(__file__).parent


class ComponentListField(Element):
    """Editable list of named components: add/remove/rename rows, live count.

    Defaults to one component ("Component 1") — always at least one, since a
    `ComponentSystem` with zero components isn't meaningful.
    """

    value = T.List(T.Unicode()).tag(sync=True)

    _esm = _DIR / "component_list_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        value: Optional[Sequence[str]] = None,
        validate: Optional[Validator] = None,
    ) -> None:
        names: List[str] = list(value) if value else ["Component 1"]
        super().__init__(label=label, value=names, validate=validate)
