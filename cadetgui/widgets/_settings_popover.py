from __future__ import annotations

from typing import Any, List

import ipywidgets as W

__all__ = ["SettingsPopover", "toggle_box"]


def toggle_box(box: W.Widget) -> bool:
    """Show/hide `box` (a `display: none` VBox); return whether it is now shown."""
    shown = box.layout.display == "none"
    box.layout.display = "" if shown else "none"
    return shown


class SettingsPopover:
    """Gear-icon button that show/hides a settings box below a section header.

    Not a real floating popover, just a plain show/hide toggle -- matches
    ARCHITECTURE.md's "no Modal element built yet" note.
    """

    def __init__(self, *, tooltip: str, children: List[Any], visible: bool = True) -> None:
        self.button = W.Button(
            icon="cog", tooltip=tooltip,
            layout=W.Layout(width="36px", display="" if visible else "none"),
        )
        self.box = W.VBox(
            [W.HTML("<div class='cadetgui-section-title'>Settings</div>"), *children],
            layout=W.Layout(display="none"),
        )
        self.box.add_class("cadetgui-section")
        self.box.add_class("cadetgui-settings-box")
        self.button.on_click(self._on_click)

    def _on_click(self, _btn: Any) -> None:
        toggle_box(self.box)

    @property
    def visible(self) -> bool:
        return self.button.layout.display != "none"

    @visible.setter
    def visible(self, value: bool) -> None:
        self.button.layout.display = "" if value else "none"
        if not value:
            self.box.layout.display = "none"
