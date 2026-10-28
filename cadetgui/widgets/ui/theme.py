"""The shared look: design tokens, the widget stylesheet and the CADET logo.

Light or dark follows the notebook host's theme (JupyterLab, Notebook 7 and Voilà mark
`body[data-jp-theme-light]`, VS Code `body.vscode-*`); only a host that says nothing falls
back to the operating system's setting.
"""

from __future__ import annotations

import base64
from pathlib import Path

__all__ = ["style_tag", "logo_data_uri", "with_tokens"]

_DIR = Path(__file__).parent
_SCOPE = ":is(.cadetgui-panel, .cadetgui-field, .cadetgui-chart, .cadetgui-table)"
_DARK_HOSTS = (
    'body[data-jp-theme-light="false"]',
    "body.vscode-dark",
    "body.vscode-high-contrast:not(.vscode-high-contrast-light)",
)
_SILENT_HOST = (
    "body:not([data-jp-theme-light]):not(.vscode-light):not(.vscode-dark)"
    ":not(.vscode-high-contrast)"
)


def _tokens() -> str:
    dark = (_DIR / "tokens_dark.css").read_text().split("*/", 1)[1].strip()
    hosts = ",\n".join(f"{host} {_SCOPE}" for host in _DARK_HOSTS)
    return (
        (_DIR / "tokens.css").read_text()
        + f"\n{hosts} {{\n{dark}\n}}\n"
        + f"@media (prefers-color-scheme: dark) {{\n{_SILENT_HOST} {_SCOPE} {{\n{dark}\n}}\n}}\n"
    )


_TOKENS = _tokens()


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
