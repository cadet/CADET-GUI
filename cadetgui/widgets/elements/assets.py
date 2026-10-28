"""Load the elements' JS views and stylesheets, inlining the shared parts."""

from __future__ import annotations

from pathlib import Path

from ..ui.theme import with_tokens

_DIR = Path(__file__).parent


def css(*names: str) -> str:
    """Text of the `<name>.css` files preceded by the shared tokens."""
    return with_tokens(*(_DIR / f"{name}.css" for name in names))


FIELD_CSS = css("shared/error", "shared/field")


def esm(name: str, *shared: str) -> str:
    """ESM source of `<name>.js` preceded by the shared JS parts.

    anywidget serves one module per widget, so shared helpers are inlined.
    """
    return "\n".join((_DIR / f"{part}.js").read_text() for part in (*shared, name))


def field_esm(name: str, *, units: bool = True) -> str:
    """ESM source of a form-field view with the field helpers (and unit renderer)."""
    units_js = ("shared/theme", "shared/unit_parser", "shared/unit_dom") if units else ()
    return esm(name, *units_js, "shared/field")
