"""Layout building blocks: panels, sections, rows, notes, collapsibles, settings, code."""

from __future__ import annotations

from html import escape
from typing import Any, Callable, List, Optional, Sequence

import ipywidgets as W

from .theme import style_tag

__all__ = [
    "panel",
    "panel_title",
    "section",
    "section_title",
    "titled_header",
    "row",
    "note",
    "collapsible",
    "toggle_box",
    "SettingsPopover",
    "CodeView",
]


def panel_title(title_html: str) -> W.HTML:
    """Return the title line of a panel; `title_html` is inserted as is."""
    return W.HTML(f"<div class='cadetgui-panel-title'>{title_html}</div>")


def section_title(title_html: str) -> W.HTML:
    """Return the title line of a section inside a panel; `title_html` is inserted as is."""
    return W.HTML(f"<div class='cadetgui-section-title'>{title_html}</div>")


def panel(title_html: Optional[str], *children: W.Widget) -> W.VBox:
    """Return a top-level widget box with the shared stylesheet and an optional title."""
    title = [panel_title(title_html)] if title_html is not None else []
    box = W.VBox([W.HTML(style_tag()), *title, *children])
    box.add_class("cadetgui-panel")
    return box


def section(
    children: Sequence[W.Widget], *classes: str, title_html: Optional[str] = None
) -> W.VBox:
    """Return a bordered section of a panel, optionally titled, with extra CSS classes."""
    title = [section_title(title_html)] if title_html is not None else []
    box = W.VBox([*title, *children])
    for cls in ("cadetgui-section", *classes):
        box.add_class(cls)
    return box


def titled_header(title_html: str, *buttons: W.Widget) -> W.HBox:
    """Return a section title with buttons at the right end of its line."""
    return W.HBox(
        [section_title(title_html), *buttons],
        layout=W.Layout(justify_content="space-between", align_items="center"),
    )


def row(*children: W.Widget) -> W.HBox:
    """Return a row of widgets that wraps on narrow screens."""
    box = W.HBox(list(children), layout=W.Layout(flex_flow="row wrap"))
    box.add_class("cadetgui-row")
    return box


def note(text_html: str = "", *, hidden: bool = False) -> W.HTML:
    """Return a small explanatory line; `hidden` starts it collapsed until text is shown."""
    widget = W.HTML(text_html, layout=W.Layout(display="none") if hidden else W.Layout())
    widget.add_class("cadetgui-note")
    return widget


def collapsible(title: str, child: W.Widget, *, open: bool = False) -> W.Accordion:
    """Return a one-item accordion around `child`, closed unless `open`."""
    accordion = W.Accordion(children=[child])
    accordion.set_title(0, title)
    accordion.selected_index = 0 if open else None
    return accordion


def toggle_box(box: W.Widget) -> bool:
    """Show/hide `box` (a `display: none` VBox); return whether it is now shown."""
    shown = box.layout.display == "none"
    box.layout.display = "" if shown else "none"
    return shown


class SettingsPopover:
    """Gear-icon button that shows or hides an inline settings box."""

    def __init__(self, *, tooltip: str, children: List[Any], visible: bool = True) -> None:
        self.button = W.Button(
            icon="cog", tooltip=tooltip,
            layout=W.Layout(width="36px", display="" if visible else "none"),
        )
        self.box = section(
            [section_title("Settings"), *children], "cadetgui-settings-box"
        )
        self.box.layout.display = "none"
        self.button.on_click(lambda _btn: toggle_box(self.box))

    @property
    def visible(self) -> bool:
        """Whether the gear button is shown."""
        return self.button.layout.display != "none"

    @visible.setter
    def visible(self, value: bool) -> None:
        self.button.layout.display = "" if value else "none"
        if not value:
            self.box.layout.display = "none"


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
