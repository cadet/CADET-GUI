from __future__ import annotations

from html import escape
from typing import Callable

import ipywidgets as W

__all__ = ["CodeView"]

# Inline, so the block keeps its look wherever the widget's stylesheet does not reach.
_PRE_STYLE = (
    "font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; "
    "line-height: 1.45; margin: 0; padding: 8px 12px; white-space: pre; overflow-x: auto; "
    "background: var(--cg-page, #f5f7fa); border: 1px solid var(--cg-border, #d1d5db); "
    "border-radius: 6px"
)


class CodeView:
    """A "Show code" toggle with the CADET-Process code that `code()` returns."""

    def __init__(self, code: Callable[[], str]) -> None:
        self._code = code
        self.toggle = W.ToggleButton(description="Show code", icon="code", value=False)
        self._body = W.HTML()
        self._body.layout.display = "none"
        self.root = W.VBox([self.toggle, self._body])
        self.toggle.observe(lambda _change: self.refresh(), names="value")

    def refresh(self) -> None:
        """Show the current code, if the toggle is on."""
        self._body.layout.display = "" if self.toggle.value else "none"
        if self.toggle.value:
            self._body.value = f'<pre style="{_PRE_STYLE}">{escape(self._code())}</pre>'
