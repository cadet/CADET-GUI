from __future__ import annotations

import html
from typing import Literal

__all__ = ["StatusKind", "status_html", "chip_html"]

StatusKind = Literal["ok", "warn", "error", "info", "running"]


def status_html(kind: StatusKind, text: str) -> str:
    """HTML for a status-line message; `text` is escaped, styling lives in chrome.css."""
    body = html.escape(text, quote=False)
    if kind == "running":
        return f"<span class='cadetgui-spinner'></span><em>{body}</em>"
    return f"<span class='cadetgui-msg cadetgui-msg-{kind}'>{body}</span>"


def chip_html(kind: StatusKind, label: str) -> str:
    """HTML for a short pill label (e.g. a run's ok/failed state)."""
    body = html.escape(label, quote=False)
    return f"<span class='cadetgui-chip cadetgui-chip-{kind}'>{body}</span>"
