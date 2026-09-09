from __future__ import annotations

import base64
from pathlib import Path

_CSS = (Path(__file__).parent / "chrome.css").read_text()
_LOGO_PNG = (Path(__file__).parent / "assets" / "cadet_logo.png").read_bytes()
_LOGO_DATA_URI = f"data:image/png;base64,{base64.b64encode(_LOGO_PNG).decode('ascii')}"


def style_tag() -> str:
    """Shared <style> HTML for composite/form widget chrome.

    See chrome.css for the class names (.cadetgui-panel, .cadetgui-section, ...).
    """
    return f"<style>{_CSS}</style>"


def logo_data_uri() -> str:
    """Return the CADET logo (icon + wordmark) as an inline `data:` URI PNG."""
    return _LOGO_DATA_URI
