from __future__ import annotations

from typing import Any, Callable, Optional

import anywidget
import traitlets as T

__all__ = ["Element"]

Validator = Callable[[Any], Optional[str]]


class Element(anywidget.AnyWidget):
    """Base for atomic input widgets: label, units, validation and error state.

    Subclasses define `value`, either as a synced trait or, when the value is not
    JSON-safe, as a property over another synced trait named by `value_trait_name`.
    """

    label = T.Unicode("").tag(sync=True)
    units = T.Unicode("").tag(sync=True)
    error = T.Unicode("").tag(sync=True)
    disabled = T.Bool(False).tag(sync=True)

    value_trait_name = "value"

    def __init__(self, *, validate: Optional[Validator] = None, **kwargs: Any) -> None:
        self._validate_fn = validate
        super().__init__(**kwargs)
        self.observe(self._run_validate, names=self.value_trait_name)
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
