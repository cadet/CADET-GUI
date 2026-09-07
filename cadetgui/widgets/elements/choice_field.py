# =========================================
# File: cadetgui/widgets/elements/choice_field.py
# =========================================
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import traitlets as T

from .base import Element, Validator

__all__ = ["ChoiceField"]

_DIR = Path(__file__).parent


class ChoiceField(Element):
    """Dropdown selecting one of several (label, value) options.

    `value` may be any Python object, not just JSON-serializable ones — only
    the option labels and the selected index cross the anywidget sync boundary;
    the label -> value mapping stays server-side (see ai-docs/ARCHITECTURE.md's
    Element contract for why).
    """

    option_labels = T.List(T.Unicode()).tag(sync=True)
    selected_index = T.Int(allow_none=True, default_value=None).tag(sync=True)

    _value_trait_name = "selected_index"

    _esm = _DIR / "choice_field.js"
    _css = _DIR / "_shared.css"

    def __init__(
        self,
        *,
        label: str = "",
        options: Sequence[Tuple[str, Any]] = (),
        value: Any = None,
        validate: Optional[Validator] = None,
    ) -> None:
        self._options: List[Tuple[str, Any]] = list(options)
        index = self._index_of(value) if value is not None else (0 if self._options else None)
        super().__init__(
            label=label,
            option_labels=[opt_label for opt_label, _ in self._options],
            selected_index=index,
            validate=validate,
        )

    def _index_of(self, value: Any) -> Optional[int]:
        for i, (_, v) in enumerate(self._options):
            if v == value:
                return i
        return None

    @property
    def value(self) -> Any:
        """The currently selected option's value (None if nothing is selected)."""
        if self.selected_index is None or not (0 <= self.selected_index < len(self._options)):
            return None
        return self._options[self.selected_index][1]

    @value.setter
    def value(self, new_value: Any) -> None:
        self.selected_index = self._index_of(new_value)

    def set_options(self, options: Sequence[Tuple[str, Any]], *, keep_value: bool = True) -> None:
        """Replace the options, optionally keeping the current value selected."""
        current = self.value if keep_value else None
        self._options = list(options)
        self.option_labels = [opt_label for opt_label, _ in self._options]
        self.selected_index = self._index_of(current) if current is not None else (
            0 if self._options else None
        )
