from __future__ import annotations

from html import escape
from typing import Any

import ipywidgets as W

from .._chrome import style_tag

__all__ = ["ComponentSystemWidget"]


class ComponentSystemWidget:
    """Read-only view of a ComponentSystem: its components and their species."""

    def __init__(self, component_system: Any) -> None:
        self.component_system = component_system
        self._body = W.HTML()
        self.root = W.VBox([W.HTML(style_tag()), self._body])
        self.root.add_class("cadetgui-panel")
        self.refresh()

    def refresh(self) -> None:
        """Show the current components."""
        rows = "".join(
            f"<tr><td>{i}</td><td>{escape(component.name)}</td>"
            f"<td>{escape(', '.join(s.name for s in component.species))}</td></tr>"
            for i, component in enumerate(self.component_system.components)
        )
        n = self.component_system.n_comp
        self._body.value = (
            f"<div class='cadetgui-panel-title'>Component system · {n} "
            f"component{'s' if n != 1 else ''}</div>"
            "<table class='cadetgui-table'><thead><tr><th>Index</th><th>Component</th>"
            f"<th>Species</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    def get_value(self) -> Any:
        """Return the ComponentSystem this widget shows."""
        return self.component_system

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
