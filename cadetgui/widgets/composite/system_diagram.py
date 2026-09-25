from __future__ import annotations

from html import escape
from typing import Collection, List, Optional, Sequence

import ipywidgets as W

from ...cadetprocessadapter import UNIT_LABELS

__all__ = ["SystemDiagram", "render_system_svg"]

_BOX_W, _BOX_H, _GAP = 88, 40, 22
_INLET_W, _INLET_H, _INLET_GAP = 76, 26, 8
_INLET_TO_MIXER = 40
_ROW_DROP = 34
_MARGIN = 12
_FONT = 11

_MAIN_PATH = (
    "mixer", "tubing_pre_injection", "sample_loop", "tubing_pre_column",
    "column", "tubing_post_column", "tubing_detectors", "outlet",
)
_JUNCTIONS = ("mixer", "tubing_pre_injection")
_BUFFERS = ("buffer_a", "buffer_b", "buffer_c", "buffer_d")

_STROKE = "var(--cg-primary, #005b82)"
_MUTED_STROKE = "var(--cg-border-strong, #7b8390)"
_FG = "var(--cg-fg, #1f2937)"
_MUTED = "var(--cg-muted, #5b6370)"
_SURFACE = "var(--cg-surface, #ffffff)"


def _lines(label: str) -> List[str]:
    head, sep, tail = label.partition(" (")
    return [head, f"({tail}"] if sep else [label]


def _node(
    unit: str, x: float, y: float, w: float, h: float, *, state: str, note: str = ""
) -> str:
    label = UNIT_LABELS.get(unit, unit.capitalize())
    lines = _lines(label)
    if note:
        lines.append(note)
    if state == "active":
        fill, stroke, text, dash = _SURFACE, _STROKE, _FG, ""
        if unit == "column":
            fill, text = _STROKE, "var(--cg-primary-fg, #ffffff)"
    else:
        fill, stroke, text, dash = "none", _MUTED_STROKE, _MUTED, ' stroke-dasharray="4 3"'
    first = y + h / 2 - (len(lines) - 1) * (_FONT + 1) / 2 + _FONT * 0.35
    tspans = "".join(
        f'<tspan x="{x + w / 2:.1f}" y="{first + i * (_FONT + 1):.1f}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<g data-unit="{unit}" data-state="{state}">'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="6" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>'
        f'<text text-anchor="middle" font-size="{_FONT}" fill="{text}">{tspans}</text>'
        "</g>"
    )


def _arrow(d: str, *, muted: bool = False) -> str:
    color = _MUTED_STROKE if muted else _STROKE
    dash = ' stroke-dasharray="4 3"' if muted else ""
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{dash} '
        f'marker-end="url(#{"cg-arrow-muted" if muted else "cg-arrow"})"/>'
    )


def _marker(marker_id: str, color: str) -> str:
    return (
        f'<marker id="{marker_id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
        f'markerHeight="7" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="{color}"/></marker>'
    )


def render_system_svg(
    units: Collection[str],
    bypassed: Collection[str] = (),
    inlets: Optional[Sequence[str]] = None,
) -> str:
    """Render the LC flow path as an HTML fragment holding one inline SVG.

    `units` are the unit names present in the flow sheet; `bypassed` the ones the user
    excluded. Bypassed units are left out of the path (the mixer, which always stays as the
    buffer junction, is drawn dashed). `inlets` are the inlet units the process drives; `None`
    means unknown, drawn as one generic inlet.
    """
    units = set(units)
    bypassed = set(bypassed)
    path = [u for u in _MAIN_PATH if u in units]

    if inlets is None:
        buffers: List[Optional[str]] = [None]
    else:
        buffers = [b for b in _BUFFERS if b in inlets]
    stack_h = len(buffers) * _INLET_H + max(len(buffers) - 1, 0) * _INLET_GAP
    band_h = max(stack_h, _BOX_H)
    yc = _MARGIN + band_h / 2
    x0 = _MARGIN + (_INLET_W + _INLET_TO_MIXER if buffers else 0)
    xs = {u: x0 + i * (_BOX_W + _GAP) for i, u in enumerate(path)}
    row2_y = _MARGIN + band_h + _ROW_DROP
    width = x0 + len(path) * _BOX_W + (len(path) - 1) * _GAP + _MARGIN
    height = row2_y + _INLET_H + _MARGIN

    parts = [_marker("cg-arrow", _STROKE), _marker("cg-arrow-muted", _MUTED_STROKE)]

    mixer_left = xs["mixer"]
    top = yc - stack_h / 2
    for i, buf in enumerate(buffers):
        y = top + i * (_INLET_H + _INLET_GAP)
        parts.append(_node(buf or "inlet", _MARGIN, y, _INLET_W, _INLET_H, state="active"))
        elbow = _MARGIN + _INLET_W + _INLET_TO_MIXER / 2
        parts.append(
            _arrow(f"M{_MARGIN + _INLET_W} {y + _INLET_H / 2:.1f} H{elbow} V{yc} H{mixer_left}")
        )

    for a, b in zip(path, path[1:]):
        parts.append(_arrow(f"M{xs[a] + _BOX_W} {yc} H{xs[b]}"))

    for unit in path:
        state = "bypassed" if unit == "mixer" and "mixer" in bypassed else "active"
        note = "bypassed" if state == "bypassed" else ""
        parts.append(_node(unit, xs[unit], yc - _BOX_H / 2, _BOX_W, _BOX_H, state=state, note=note))

    junction = [u for u in _JUNCTIONS if u in path][-1]
    if "waste" in units:
        cx = xs[junction] + _BOX_W / 2
        parts.append(_arrow(f"M{cx} {yc + _BOX_H / 2} V{row2_y}", muted=True))
        parts.append(
            _node("waste", cx - _BOX_W / 2, row2_y, _BOX_W, _INLET_H, state="idle")
        )

    if inlets is not None and "feed_inlet" in inlets:
        target = next(u for u in path if u not in _JUNCTIONS)
        cx = xs[target] + _BOX_W / 2
        parts.append(_arrow(f"M{cx} {row2_y} V{yc + _BOX_H / 2}"))
        parts.append(
            _node("feed_inlet", cx - _INLET_W / 2, row2_y, _INLET_W, _INLET_H, state="active")
        )

    off = [UNIT_LABELS[u] for u in _MAIN_PATH if u in bypassed and u in UNIT_LABELS]
    caption = (
        f'<div style="font-size:12px;color:{_MUTED};margin-top:4px">'
        f"Not in the flow path: {escape(', '.join(off))}</div>"
        if off
        else ""
    )
    return (
        f'<div class="cadetgui-system-diagram">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Flow path of the LC system" '
        f'style="width:100%;max-width:{width:.0f}px;height:auto;display:block" '
        f'font-family="var(--cg-font, system-ui, sans-serif)">'
        f'{"".join(parts)}</svg>{caption}</div>'
    )


class SystemDiagram:
    """Read-only schematic of the current LC flow path."""

    def __init__(self) -> None:
        self.root = W.HTML("")
        self.update(None)

    def update(
        self,
        flow_sheet: object,
        bypassed: Collection[str] = (),
        inlets: Optional[Sequence[str]] = None,
    ) -> None:
        """Redraw for `flow_sheet` (a built LCFlowSheet, or `None` while inputs are invalid)."""
        if flow_sheet is None:
            self.root.value = (
                f'<em style="color:{_MUTED}">No system to show while inputs are invalid.</em>'
            )
            return
        self.root.value = render_system_svg(flow_sheet.units_dict, bypassed, inlets)
