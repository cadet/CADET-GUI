"""HTML snippets for status lines, tables, help boxes and checklists."""

from __future__ import annotations

import html
from typing import Literal, Optional, Sequence

__all__ = [
    "StatusKind",
    "status_html",
    "table_html",
    "info_box_html",
    "checklist_html",
]

StatusKind = Literal["ok", "warn", "error", "info", "running"]


def status_html(kind: StatusKind, text: str) -> str:
    """HTML for a status-line message; `text` is escaped, styling lives in chrome.css."""
    body = html.escape(text, quote=False)
    if kind == "running":
        return f"<span class='cadetgui-spinner'></span><em>{body}</em>"
    return f"<span class='cadetgui-msg cadetgui-msg-{kind}'>{body}</span>"


def table_html(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    css_class: str = "cadetgui-table",
    empty_html: Optional[str] = None,
) -> str:
    """Return a table; headers and cells are inserted as is, so escape plain text first."""
    if not rows and empty_html is not None:
        return empty_html
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return (
        f"<table class='{css_class}'><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def info_box_html(title: str, body_html: str, *, open: bool = False) -> str:
    """Return a collapsible help box; `body_html` is inserted as is, `title` is escaped."""
    state = " open" if open else ""
    return (
        f"<details class='cadetgui-info'{state}>"
        f"<summary>{html.escape(title, quote=False)}</summary>"
        f"<div class='cadetgui-info-body'>{body_html}</div></details>"
    )


def checklist_html(items: Sequence[str]) -> str:
    """Return `items` as an escaped bullet list."""
    rows = "".join(f"<li>{html.escape(item, quote=False)}</li>" for item in items)
    return f"<ul class='cadetgui-checklist'>{rows}</ul>"
