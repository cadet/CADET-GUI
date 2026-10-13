"""The base class of cadetgui's composite widgets."""

from __future__ import annotations

from typing import Any, Callable, List

import ipywidgets as W

__all__ = ["Widget"]


class Widget:
    """A widget built from ipywidgets under one `root`, with change listeners.

    Subclasses set `self.root` and call `self._notify(...)` when their value changes.
    An instance displays itself as the last expression of a notebook cell, or via
    `display()`.
    """

    root: W.Widget

    def __init__(self) -> None:
        self._listeners: List[Callable[..., None]] = []

    def add_listener(self, fn: Callable[..., None]) -> None:
        """Call `fn` whenever this widget's value changes."""
        self._listeners.append(fn)

    def _notify(self, *args: Any) -> None:
        for fn in list(self._listeners):
            fn(*args)

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display

        display(self.root)

    def _repr_mimebundle_(self, **kwargs: Any) -> Any:
        return self.root._repr_mimebundle_(**kwargs)
