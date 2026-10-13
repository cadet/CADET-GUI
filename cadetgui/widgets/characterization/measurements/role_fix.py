"""Warning that a component's role does not fit, with a button that changes the role."""

from __future__ import annotations

from typing import Optional, Tuple

import ipywidgets as W

from ...ui.html import status_html
from ...ui.layout import row

__all__ = ["RoleFixPrompt"]


class RoleFixPrompt:
    """Show `role_fix` text and a "Make <name> a <role>" button; the host handles clicks."""

    def __init__(self) -> None:
        self.text = W.HTML()
        self.button = W.Button(
            icon="exchange", button_style="warning",
            layout=W.Layout(width="auto", display="none"),
        )
        self.target: Optional[Tuple[str, str]] = None
        self.root = row(self.text, self.button)

    def show(self, name: Optional[str], text: str, role: Optional[str]) -> None:
        """Show `text`; offer the button when `role` is a role `name` could take."""
        self.target = (name, role) if role is not None and name else None
        self.text.value = status_html("warn", text) if text else ""
        if self.target is not None:
            self.button.description = f"Make {name} a {role}"
        self.button.layout.display = "" if self.target is not None else "none"
