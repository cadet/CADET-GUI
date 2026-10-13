"""Building blocks shared by all widgets: theme, layout, HTML snippets, formatting, plots."""

from .format import unit_html
from .html import StatusKind, checklist_html, info_box_html, status_html, table_html
from .layout import (
    CodeView,
    SettingsPopover,
    collapsible,
    note,
    panel,
    panel_title,
    row,
    section,
    section_title,
    titled_header,
    toggle_box,
)
from .theme import logo_data_uri, style_tag

__all__ = [
    "CodeView",
    "SettingsPopover",
    "StatusKind",
    "checklist_html",
    "collapsible",
    "info_box_html",
    "logo_data_uri",
    "note",
    "panel",
    "panel_title",
    "row",
    "section",
    "section_title",
    "status_html",
    "style_tag",
    "table_html",
    "titled_header",
    "toggle_box",
    "unit_html",
]
