"""P&ID symbols and the SVG drawing primitives the diagrams share."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from html import escape, unescape
from importlib import resources
from typing import Sequence

FG = "var(--cg-fg, #1f2937)"
MUTED = "var(--cg-muted, #5b6370)"
MUTED_STROKE = "var(--cg-border-strong, #7b8390)"
SURFACE = "var(--cg-surface, #ffffff)"

_LIGHT_DARK = (
    ("light-dark(rgb(0, 0, 0), rgb(255, 255, 255))", FG),
    ("light-dark(#ffffff, var(--ge-dark-color, #121212))", SURFACE),
)


@dataclass(frozen=True)
class Symbol:
    """One P&ID symbol: its SVG body and text, and its size."""

    name: str
    width: float
    height: float
    body: str
    text: str


_SWITCH = re.compile(
    r"<switch>\s*<foreignObject\b.*?</foreignObject>\s*"
    r'<image x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"[^>]*/>\s*</switch>',
    re.S,
)
_EMPTY_GROUP = re.compile(r"<g(?:\s[^>]*)?/>|<g(?:\s[^>]*)?>\s*</g>")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _label_as_text(match: re.Match) -> str:
    fo = match.group(0)
    fo = fo[: fo.index("</foreignObject>")]
    x, y, w, h = (float(match.group(i)) for i in range(1, 5))
    sizes = re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", fo)
    size = float(sizes[-1]) if sizes else 12.0
    plain = unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", fo)))
    lines = [line.strip() for line in _CONTROL.sub("", plain).split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    bold = ' font-weight="bold"' if "<b" in fo or "font-weight: bold" in fo else ""
    underline = ' text-decoration="underline"' if "<u" in fo else ""
    y0 = y + h / 2 - (len(lines) - 1) * size * 0.6
    tspans = "".join(
        f'<tspan x="{x + w / 2:g}" y="{y0 + i * size * 1.2:g}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="middle" dominant-baseline="central" font-size="{size:g}"'
        f'{bold}{underline} style="fill: {FG}">{tspans}</text>'
    )


@lru_cache(maxsize=None)
def load_symbol(name: str) -> Symbol:
    """Read a shipped P&ID symbol and reduce it to theme-aware, standalone SVG content."""
    raw = (
        resources.files("cadetgui") / "assets" / "pid" / f"{name}.drawio.svg"
    ).read_text(encoding="utf-8")
    root = re.search(r"<svg\b[^>]*>", raw, re.S)
    if root is None:
        raise ValueError(f"{name}: not an SVG file")
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', root.group(0))
    if box is None:
        raise ValueError(f"{name}: SVG has no viewBox")
    body = raw[root.end() : raw.rindex("</svg>")]
    body = body.replace("<defs/>", "")
    body = re.sub(r'<rect fill="#ffffff" width="100%" height="100%"[^>]*/>', "", body)
    body = _SWITCH.sub(_label_as_text, body)
    for old, new in _LIGHT_DARK:
        body = body.replace(old, new)
    body = re.sub(
        r' (?:data-cell-id|pointer-events|stroke-miterlimit)="[^"]*"', "", body
    )
    body = re.sub(r"[ \t]*\n[ \t]*", "", body)
    body, n = _EMPTY_GROUP.subn("", body)
    while n:
        body, n = _EMPTY_GROUP.subn("", body)
    texts = re.findall(r"<tspan[^>]*>([^<]*)</tspan>", body)
    return Symbol(
        name,
        float(box.group(1)),
        float(box.group(2)),
        body,
        unescape(texts[0]) if texts else "",
    )


# Port geometry inside each symbol: (x of the left port, x of the right port, y of the flow line).
PORTS = {
    "Mixer": (0.5, 60.5, 57.5),
    "Column": (0.5, 320.5, 40.5),
    "SampleLoop": (50.5, 100.5, 195.5),
    "Outlet": (0.5, 0.5, 50.5),
    "Inlet": (80.5, 80.5, 50.5),
}
TUBE_WIDTH = 3
LINE_WIDTH = 1.5
CAPTION_FONT = 14
CAPTION_LEAD = 16


def num(value: float) -> str:
    """Format a coordinate with at most one decimal."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def place_symbol(name: str, x: float, y: float) -> str:
    """Place P&ID symbol `name` with its top left corner at (x, y)."""
    sym = load_symbol(name)
    return (
        f'<svg data-symbol="{name}" x="{num(x)}" y="{num(y)}" width="{num(sym.width)}" '
        f'height="{num(sym.height)}" viewBox="0 0 {num(sym.width)} {num(sym.height)}">'
        f"{sym.body}</svg>"
    )


def text_block(
    lines: Sequence[str],
    cx: float,
    y: float,
    *,
    italic: bool = False,
    start: bool = False,
    strong: bool = False,
) -> str:
    """Return a text block of `lines` centred on (or starting at) `cx`."""
    style = ' font-style="italic"' if italic else ""
    anchor = "start" if start else "middle"
    weight = ' font-weight="bold"' if strong else ""
    tspans = "".join(
        f'<tspan x="{num(cx)}" y="{num(y + i * CAPTION_LEAD)}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="{anchor}" font-size="{CAPTION_FONT}"{style}{weight} '
        f'style="fill: {FG if strong else MUTED}">{tspans}</text>'
    )


def arrow_marker(marker_id: str, color: str) -> str:
    """Return an arrow-head marker definition."""
    return (
        f'<marker id="{marker_id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
        f'markerHeight="7" orient="auto">'
        f'<path d="M0 0 L8 4 L0 8 z" style="fill: {color}"/></marker>'
    )


def flow_line(
    d: str, *, muted: bool = False, arrow: bool = True, width: float = LINE_WIDTH
) -> str:
    """Return a flow line along path `d`; muted ones are dashed."""
    color = MUTED_STROKE if muted else FG
    dash = ' stroke-dasharray="5 4"' if muted else ""
    end = (
        f' marker-end="url(#{"cg-arrow-muted" if muted else "cg-arrow"})"'
        if arrow
        else ""
    )
    return (
        f'<path d="{d}" fill="none" style="stroke: {color}" '
        f'stroke-width="{width:g}"{dash}{end}/>'
    )


def tube_segment(x1: float, x2: float, y: float) -> str:
    """Return a horizontal tubing segment from x1 to x2."""
    return flow_line(f"M{num(x1)} {num(y)} H{num(x2)}", arrow=False, width=TUBE_WIDTH)
