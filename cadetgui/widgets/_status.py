from __future__ import annotations

import html
from typing import Literal

__all__ = ["StatusKind", "status_html"]

StatusKind = Literal["ok", "warn", "error", "info", "running"]


def status_html(kind: StatusKind, text: str) -> str:
    """HTML for a status-line message; `text` is escaped, styling lives in chrome.css."""
    body = html.escape(text, quote=False)
    if kind == "running":
        return f"<span class='cadetgui-spinner'></span><em>{body}</em>"
    return f"<span class='cadetgui-msg cadetgui-msg-{kind}'>{body}</span>"
