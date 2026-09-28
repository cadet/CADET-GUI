from __future__ import annotations

import base64
from pathlib import Path

from ._tokens import with_tokens

_CSS = with_tokens(Path(__file__).parent / "chrome.css")
_LOGO_PNG = (Path(__file__).parent / "assets" / "cadet_logo.png").read_bytes()
_LOGO_DATA_URI = f"data:image/png;base64,{base64.b64encode(_LOGO_PNG).decode('ascii')}"


def style_tag() -> str:
    """<style> tag with the shared widget chrome (see chrome.css)."""
    return f"<style>{_CSS}</style>"


def logo_data_uri() -> str:
    """Return the CADET logo as an inline PNG `data:` URI."""
    return _LOGO_DATA_URI
