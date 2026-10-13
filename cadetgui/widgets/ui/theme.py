"""The shared look: design tokens, the widget stylesheet and the CADET logo."""

from __future__ import annotations

import base64
from pathlib import Path

__all__ = ["style_tag", "logo_data_uri", "with_tokens"]

_DIR = Path(__file__).parent
_TOKENS = (_DIR / "tokens.css").read_text()


def with_tokens(*paths: Path) -> str:
    """Concatenate the shared design tokens and the given stylesheets."""
    return "\n".join([_TOKENS, *(path.read_text() for path in paths)])


_CSS = with_tokens(_DIR / "chrome.css")
_LOGO_PNG = (_DIR / "cadet_logo.png").read_bytes()
_LOGO_DATA_URI = f"data:image/png;base64,{base64.b64encode(_LOGO_PNG).decode('ascii')}"


def style_tag() -> str:
    """Return a <style> tag with the shared widget chrome (see chrome.css)."""
    return f"<style>{_CSS}</style>"


def logo_data_uri() -> str:
    """Return the CADET logo as an inline PNG `data:` URI."""
    return _LOGO_DATA_URI
