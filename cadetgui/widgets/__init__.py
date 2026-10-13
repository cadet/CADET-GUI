"""Widgets for CADET-GUI.

- `Widget` (base): the base class of every composite widget
- `ui`: shared building blocks (theme, layout, HTML snippets, formatting, plots, shell)
- `elements`: atomic anywidget inputs and charts
- `forms`: FormRenderer, rendering a ModelSpec into elements
- `diagrams`: P&ID-style SVG diagrams
- `process_model`, `instrument`, `estimation`, `characterization`: widgets per domain
- `benches`: the ready-made workbenches and their frame

At this level: `Widget` and the kit for building a bench of your own.
"""
from .base import Widget
from .benches.frame import bench_root
from .ui.html import StatusKind, checklist_html, info_box_html, status_html, table_html
from .ui.layout import CodeView, SettingsPopover, collapsible, note, panel, row, section
from .ui.shell import (
    SYSTEM_GROUP,
    SidebarShell,
    collect_panes,
    resolve_step,
    system_pane_label,
    validate_steps,
)
from .ui.theme import style_tag

__all__ = [
    "Widget",
    "SidebarShell",
    "bench_root",
    "SYSTEM_GROUP",
    "system_pane_label",
    "resolve_step",
    "validate_steps",
    "collect_panes",
    "panel",
    "section",
    "row",
    "note",
    "collapsible",
    "SettingsPopover",
    "CodeView",
    "StatusKind",
    "status_html",
    "table_html",
    "info_box_html",
    "checklist_html",
    "style_tag",
]
