from __future__ import annotations

from typing import Any, Callable, Optional

import anywidget
import traitlets as T

__all__ = ["Element"]

Validator = Callable[[Any], Optional[str]]


class Element(anywidget.AnyWidget):
    """Base for atomic input widgets: value + label + validation, synced to JS.

    Implements the element contract from ai-docs/ARCHITECTURE.md: state via
    `error`/`is_valid`, events via traitlets' own `.observe()`. Subclasses define
    their own `value` — either a synced trait directly (`FloatField`, `TextField`,
    ...) for JSON-safe types, or a plain Python property backed by a different
    synced trait (`ChoiceField.selected_index`) when the true value isn't
    JSON-serializable (e.g. an arbitrary Python/CADET-Process object) and must
    stay server-side. Set `_value_trait_name` to the synced trait that should
    trigger re-validation in the latter case.
    """

    label = T.Unicode("").tag(sync=True)
    units = T.Unicode("").tag(sync=True)
    error = T.Unicode("").tag(sync=True)

    _value_trait_name = "value"

    def __init__(self, *, validate: Optional[Validator] = None, **kwargs: Any) -> None:
        self._validate_fn = validate
        super().__init__(**kwargs)
        self.observe(self._run_validate, names=self._value_trait_name)
        self._run_validate()

    def _run_validate(self, change: Optional[dict] = None) -> None:
        if self._validate_fn is None:
            return
        try:
            message = self._validate_fn(self.value)
        except ValueError as exc:
            message = str(exc)
        self.error = message or ""

    @property
    def is_valid(self) -> bool:
        """Whether the current value passed validation."""
        return not self.error
