from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from html import escape, unescape
from importlib import resources
from typing import Collection, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W

from ...cadetprocessadapter import UNIT_LABELS

__all__ = ["SystemDiagram", "render_system_svg"]

_MAIN_PATH = (
    "mixer",
    "tubing_pre_injection",
    "sample_loop",
    "tubing_pre_column",
    "column",
    "tubing_post_column",
    "tubing_detectors",
    "outlet",
)
_JUNCTIONS = ("mixer", "tubing_pre_injection")
_BUFFERS = ("buffer_a", "buffer_b", "buffer_c", "buffer_d")

_SYMBOL_OF = {
    "buffer_a": "InletA",
    "buffer_b": "InletB",
    "buffer_c": "InletC",
    "buffer_d": "InletD",
    "feed_inlet": "Inlet",
    "inlet": "Inlet",
    "mixer": "Mixer",
    "sample_loop": "SampleLoop",
    "column": "Column",
    "outlet": "Outlet",
    "waste": "Outlet",
}

# Port geometry inside each symbol: (x of the left port, x of the right port, y of the flow line).
_PORTS = {
    "Mixer": (0.5, 60.5, 57.5),
    "Column": (0.5, 320.5, 40.5),
    "SampleLoop": (50.5, 100.5, 195.5),
    "Outlet": (0.5, 0.5, 50.5),
    "Inlet": (80.5, 80.5, 50.5),
}
_LOOP_IN_Y = 145.5
_LOOP_SAMPLE_PORT = (152.8, 80.5)
_STEM = (30.5, 95.5)
_FEED_RISE = _PORTS["SampleLoop"][2] - _LOOP_SAMPLE_PORT[1] + _PORTS["Inlet"][2]

_GAP = 28
_TUBE = 80
_TUBE_WIDTH = 3
_LINE_WIDTH = 1.5
_MARGIN = 16
_BUS = 30
_INLET_GAP = 40
_ROW_DROP = 40
_CAPTION_FONT = 14
_CAPTION_LEAD = 16

_FG = "var(--cg-fg, #1f2937)"
_MUTED = "var(--cg-muted, #5b6370)"
_MUTED_STROKE = "var(--cg-border-strong, #7b8390)"
_SURFACE = "var(--cg-surface, #ffffff)"

_LIGHT_DARK = (
    ("light-dark(rgb(0, 0, 0), rgb(255, 255, 255))", _FG),
    ("light-dark(#ffffff, var(--ge-dark-color, #121212))", _SURFACE),
)


@dataclass(frozen=True)
class _Symbol:
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
        f'{bold}{underline} style="fill: {_FG}">{tspans}</text>'
    )


@lru_cache(maxsize=None)
def _load_symbol(name: str) -> _Symbol:
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
    return _Symbol(
        name,
        float(box.group(1)),
        float(box.group(2)),
        body,
        unescape(texts[0]) if texts else "",
    )


def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _symbol(name: str, x: float, y: float) -> str:
    sym = _load_symbol(name)
    return (
        f'<svg data-symbol="{name}" x="{_num(x)}" y="{_num(y)}" width="{_num(sym.width)}" '
        f'height="{_num(sym.height)}" viewBox="0 0 {_num(sym.width)} {_num(sym.height)}">'
        f"{sym.body}</svg>"
    )


def _lines(label: str) -> List[str]:
    head, sep, tail = label.partition(" (")
    return [head, f"({tail}"] if sep else [label]


def _caption(
    lines: Sequence[str],
    cx: float,
    y: float,
    *,
    italic: bool = False,
    start: bool = False,
    strong: bool = False,
) -> str:
    style = ' font-style="italic"' if italic else ""
    anchor = "start" if start else "middle"
    weight = ' font-weight="bold"' if strong else ""
    tspans = "".join(
        f'<tspan x="{_num(cx)}" y="{_num(y + i * _CAPTION_LEAD)}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="{anchor}" font-size="{_CAPTION_FONT}"{style}{weight} '
        f'style="fill: {_FG if strong else _MUTED}">{tspans}</text>'
    )


def _marker(marker_id: str, color: str) -> str:
    return (
        f'<marker id="{marker_id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
        f'markerHeight="7" orient="auto">'
        f'<path d="M0 0 L8 4 L0 8 z" style="fill: {color}"/></marker>'
    )


def _wire(
    d: str, *, muted: bool = False, arrow: bool = True, width: float = _LINE_WIDTH
) -> str:
    color = _MUTED_STROKE if muted else _FG
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


@dataclass
class _Item:
    unit: str
    state: str
    x: float
    width: float
    in_x: float
    out_x: float
    up: float
    down: float
    symbol: Optional[str]


def _item(unit: str, x: float, state: str) -> _Item:
    if unit == "tubing_detectors":
        width = 2 * _load_symbol("UVSensor").width + 3 * 20
        return _Item(unit, state, x, width, 0, width, _STEM[1] + 2, 0, None)
    if unit.startswith("tubing"):
        return _Item(unit, state, x, _TUBE, 0, _TUBE, 0, 0, None)
    name = _SYMBOL_OF[unit]
    sym = _load_symbol(name)
    in_x, out_x, port_y = _PORTS[name]
    return _Item(
        unit, state, x, sym.width, in_x, out_x, port_y, sym.height - port_y, name
    )


def _label_of(unit: str) -> str:
    return UNIT_LABELS.get(unit, unit.capitalize())


def _extent(it: _Item, note: str) -> Tuple[float, float]:
    """Return how far the item, captions included, reaches above and below the flow line."""
    label_lines = len(_lines(_label_of(it.unit)))
    if it.unit == "tubing_detectors":
        return it.up, 20 + (label_lines - 1) * _CAPTION_LEAD + 6
    if it.symbol is None:
        return 12 + label_lines * _CAPTION_LEAD, 0
    up, down = it.up, it.down
    if note:
        up += 6 + _CAPTION_FONT
    if _label_of(it.unit) != _load_symbol(it.symbol).text:
        down += 8 + label_lines * _CAPTION_LEAD
    return up, down


def _tube(x1: float, x2: float, y: float) -> str:
    return _wire(f"M{_num(x1)} {_num(y)} H{_num(x2)}", arrow=False, width=_TUBE_WIDTH)


def _draw_item(it: _Item, my: float, note: str) -> str:
    label = _label_of(it.unit)
    lines = _lines(label)
    cx = it.x + it.width / 2

    if it.unit == "tubing_detectors":
        sensor_w = _load_symbol("UVSensor").width
        parts = [_tube(it.x, it.x + it.width, my)]
        for name, dx in (("UVSensor", 20), ("CondSensor", 40 + sensor_w)):
            parts.append(_symbol(name, it.x + dx, my - _STEM[1]))
            parts.append(
                f'<circle cx="{_num(it.x + dx + _STEM[0])}" cy="{_num(my)}" r="4" '
                f'style="fill: {_SURFACE}; stroke: {_FG}" stroke-width="1"/>'
            )
        parts.append(_caption(lines, cx, my + 20))
        return "".join(parts)

    if it.symbol is None:
        first = my - 12 - (len(lines) - 1) * _CAPTION_LEAD
        return _tube(it.x, it.x + it.width, my) + _caption(lines, cx, first)

    sym = _load_symbol(it.symbol)
    sy = my - _PORTS[it.symbol][2]
    inner = _symbol(it.symbol, it.x, sy)
    if it.state == "bypassed":
        parts = [
            f'<g opacity="0.4">{inner}</g>',
            f'<rect x="{_num(it.x)}" y="{_num(sy)}" width="{_num(sym.width)}" '
            f'height="{_num(sym.height)}" rx="4" fill="none" style="stroke: {_MUTED_STROKE}" '
            f'stroke-width="1.5" stroke-dasharray="5 4"/>',
        ]
    else:
        parts = [inner]
    if note:
        parts.append(_caption([note], cx, sy - 6, italic=True))
    if label != sym.text:
        parts.append(_caption(lines, cx, sy + sym.height + 16))
    return "".join(parts)


def _unit_group(unit: str, state: str, content: str) -> str:
    return f'<g data-unit="{unit}" data-state="{state}">{content}</g>'


def _dim(content: str, on: bool) -> str:
    return content if on else f'<g opacity="0.4">{content}</g>'


def _names(names: Sequence[str]) -> str:
    text = ", ".join(names)
    return text if len(text) <= 24 else f"{len(names)} components"


def _inlet_lines(unit: str, on: bool, carries: Optional[Mapping[str, Sequence[str]]]) -> List[str]:
    if unit == "feed_inlet":
        head = ["Feed inlet", "(sample components)"]
        names = (carries or {}).get(unit)
        if not on:
            return [*head, "unused"]
        return [*head, _names(names)] if names else head
    label = _label_of(unit)
    if not on:
        return [label, "(unused)"]
    if carries is None or unit not in carries:
        return [label]
    return [label, f"({_names(carries[unit])})" if carries[unit] else "(buffer only)"]


def _letters(units: Sequence[str]) -> str:
    letters = [u[-1].upper() for u in units]
    if len(letters) == len(_BUFFERS):
        return "A\u2013D"
    return letters[0] if len(letters) == 1 else ", ".join(letters[:-1]) + " and " + letters[-1]


def _usage_notes(
    inlets: Collection[str],
    carries: Optional[Mapping[str, Sequence[str]]],
    shown: Collection[str],
    path: Collection[str],
    mixer_on: bool = True,
) -> List[str]:
    """One plain-language sentence per active inlet group, then what is not used."""
    carries = carries or {}
    target = "the column" if "column" in path else "the flow path"
    notes: List[str] = []
    if "feed_inlet" in inlets:
        names = carries.get("feed_inlet", [])
        what = f" ({', '.join(names)})" if names else ""
        via = "through the sample loop" if "sample_loop" in path else "straight"
        notes.append(f"Feed inlet carries the sample components{what} {via} into {target}.")
    on = [b for b in _BUFFERS if b in inlets]
    if on:
        names = list(dict.fromkeys(n for b in on for n in carries.get(b, [])))
        what = ", ".join(names) if names else "plain buffer"
        noun, verb = ("Buffer", "carries") if len(on) == 1 else ("Buffers", "carry")
        via = " through the mixer" if mixer_on else ""
        notes.append(f"{noun} {_letters(on)} {verb} {what}{via} into {target}.")
    if carries.get("sample_loop") and "sample_loop" in path:
        notes.append(
            f"The sample ({', '.join(carries['sample_loop'])}) is pre-filled in the sample "
            f"loop and injected onto {target}."
        )
    off = []
    if "feed_inlet" in shown and "feed_inlet" not in inlets:
        off.append("the feed inlet")
    off_buffers = [b for b in _BUFFERS if b in shown and b not in inlets]
    if off_buffers:
        off.append(f"buffer{'' if len(off_buffers) == 1 else 's'} {_letters(off_buffers)}")
    if off:
        notes.append(f"Not used: {' and '.join(off)}.")
    return notes


def render_system_svg(
    units: Collection[str],
    bypassed: Collection[str] = (),
    inlets: Optional[Sequence[str]] = None,
    carries: Optional[Mapping[str, Sequence[str]]] = None,
) -> str:
    """Render the LC flow path from the P&ID symbols as an HTML fragment holding one SVG.

    `units` are the unit names present in the flow sheet; `bypassed` the ones the user
    excluded. Bypassed units are left out of the path (the mixer, which always stays as the
    buffer junction, is drawn dimmed and dashed). `inlets` are the inlet units the process
    drives; `None` means unknown, drawn as one generic inlet. Every buffer inlet and the feed
    inlet of the flow sheet is drawn, the ones outside `inlets` dimmed and marked unused.
    `carries` maps an inlet (and `"sample_loop"`) to the component names it delivers and adds
    them to the labels and to a plain-language caption under the drawing.
    """
    units = set(units)
    bypassed = set(bypassed)
    path = [u for u in _MAIN_PATH if u in units]
    has_loop = "sample_loop" in path
    known = inlets is not None
    active = set(inlets or ())
    if known:
        buffers = [b for b in _BUFFERS if b in units or b in active]
        active_buffers = [b for b in buffers if b in active]
    else:
        buffers = active_buffers = ["inlet"]
    feed_shown = known and ("feed_inlet" in units or "feed_inlet" in active)
    feed_on = feed_shown and "feed_inlet" in active
    inlet_sym = _load_symbol("Inlet")
    feed_lines = _inlet_lines("feed_inlet", feed_on, carries if known else None)
    feed_extra = (len(feed_lines) - 1) * _CAPTION_LEAD

    pitch = inlet_sym.height + _INLET_GAP
    stack_h = max(len(buffers) * pitch - _INLET_GAP, 0)
    heading = 24 if known and buffers else 0
    x0 = _MARGIN + (inlet_sym.width + _BUS + 25 if buffers else 0)

    items: List[_Item] = []
    x = x0
    for unit in path:
        state = "bypassed" if unit == "mixer" and "mixer" in bypassed else "active"
        it = _item(unit, x, state)
        items.append(it)
        x += it.width + _GAP

    up_max = stack_h / 2 + 4 + heading
    if feed_shown and has_loop:
        up_max = max(up_max, _FEED_RISE + 6 + feed_extra + _CAPTION_FONT)
    item_down = 0.0
    for it in items:
        up, down = _extent(it, "bypassed" if it.state == "bypassed" else "")
        up_max, item_down = max(up_max, up), max(item_down, down)
    my = _MARGIN + up_max

    junction = next((it for it in reversed(items) if it.unit in _JUNCTIONS), None)
    target = next((it for it in items if it.unit not in _JUNCTIONS), None)
    row2_y = my + item_down + _ROW_DROP
    parts = [_marker("cg-arrow", _FG), _marker("cg-arrow-muted", _MUTED_STROKE)]
    right = x - _GAP

    first = items[0] if items else None
    bus_x = _MARGIN + inlet_sym.width + _BUS
    if buffers and first is not None:
        top = my - stack_h / 2
        if known:
            head = _caption(
                ["Buffers via mixer"], _MARGIN, top - 12, start=True, strong=bool(active_buffers)
            )
            parts.append(head)
        ys = {}
        for i, buf in enumerate(buffers):
            y = top + i * pitch
            on = buf in active_buffers
            content = _dim(_symbol(_SYMBOL_OF[buf], _MARGIN, y), on)
            lines = _inlet_lines(buf, on, carries) if known else _lines(_label_of(buf))
            if known or _label_of(buf) != _load_symbol(_SYMBOL_OF[buf]).text:
                content += _caption(
                    lines, _MARGIN + inlet_sym.width / 2, y + inlet_sym.height + 16
                )
            parts.append(_unit_group(buf, "active" if on else "unused", content))
            ys[buf] = y + _PORTS["Inlet"][2]
            parts.append(
                _wire(
                    f"M{_num(_MARGIN + inlet_sym.width - 0.5)} {_num(ys[buf])} H{_num(bus_x)}",
                    arrow=False,
                    muted=not on,
                )
            )
        on_ys = [ys[b] for b in active_buffers] + [my]
        all_ys = list(ys.values()) + [my]
        if max(all_ys) > min(all_ys) and len(active_buffers) < len(buffers):
            parts.append(
                _wire(f"M{_num(bus_x)} {_num(min(all_ys))} V{_num(max(all_ys))}",
                      arrow=False, muted=True)
            )
        if active_buffers and max(on_ys) > min(on_ys):
            parts.append(
                _wire(f"M{_num(bus_x)} {_num(min(on_ys))} V{_num(max(on_ys))}", arrow=False)
            )
        parts.append(
            _wire(
                f"M{_num(bus_x)} {_num(my)} H{_num(first.x + first.in_x)}",
                muted=not active_buffers,
            )
        )

    for a, b in zip(items, items[1:]):
        x1 = a.x + a.out_x
        if b.unit == "sample_loop":
            x2 = b.x + b.in_x
            y2 = my - (_PORTS["SampleLoop"][2] - _LOOP_IN_Y)
            d = f"M{_num(x1)} {_num(my)} H{_num(x2)} V{_num(y2)}"
        else:
            d = f"M{_num(x1)} {_num(my)} H{_num(b.x + b.in_x)}"
        parts.append(_wire(d, arrow=b.symbol is not None))

    for it in items:
        note = "bypassed" if it.state == "bypassed" else ""
        parts.append(_unit_group(it.unit, it.state, _draw_item(it, my, note)))

    if "waste" in units and junction is not None:
        cx = junction.x + junction.width / 2
        start = my + junction.down
        wx = cx - inlet_sym.width / 2
        content = _symbol("Outlet", wx, row2_y)
        label = _label_of("waste")
        content += _caption([label], cx, row2_y + inlet_sym.height + 16)
        parts.append(_wire(f"M{_num(cx)} {_num(start)} V{_num(row2_y)}", muted=True))
        parts.append(_unit_group("waste", "idle", content))
        right = max(right, wx + inlet_sym.width)

    feed_state = "active" if feed_on else "unused"
    if feed_shown and has_loop:
        loop = next(it for it in items if it.unit == "sample_loop")
        fx = loop.x + loop.width + _GAP
        fy = my - _FEED_RISE
        content = _dim(_symbol("Inlet", fx, fy), feed_on)
        content += _caption(feed_lines, fx + inlet_sym.width / 2, fy - 6 - feed_extra)
        sample_x = loop.x + _LOOP_SAMPLE_PORT[0]
        parts.append(
            _wire(
                f"M{_num(fx + 0.5)} {_num(fy + _PORTS['Inlet'][2])} H{_num(sample_x)}",
                arrow=False,
                muted=not feed_on,
            )
        )
        parts.append(_unit_group("feed_inlet", feed_state, content))
        right = max(right, fx + inlet_sym.width)
    elif feed_shown and target is not None:
        cx = target.x + target.width / 2
        fx = cx - inlet_sym.width / 2
        end = my + (target.down if target.symbol else 1)
        content = _dim(_symbol("Inlet", fx, row2_y), feed_on)
        content += _caption(feed_lines, cx, row2_y + inlet_sym.height + 16)
        parts.append(_wire(f"M{_num(cx)} {_num(row2_y)} V{_num(end)}", muted=not feed_on))
        parts.append(_unit_group("feed_inlet", feed_state, content))
        right = max(right, fx + inlet_sym.width)

    width = right + _MARGIN
    bottom = max(my + item_down, my + stack_h / 2 + 24 + (_CAPTION_LEAD if known else 0))
    if ("waste" in units and junction is not None) or (feed_shown and not has_loop):
        below = row2_y + inlet_sym.height + 24 + (feed_extra if feed_shown and not has_loop else 0)
        bottom = max(bottom, below)
    height = bottom + _MARGIN

    shown = set(buffers) | ({"feed_inlet"} if feed_shown else set())
    notes = _usage_notes(active, carries, shown, path, "mixer" not in bypassed) if known else []
    off = [UNIT_LABELS[u] for u in _MAIN_PATH if u in bypassed and u in UNIT_LABELS]
    if off:
        notes.append(f"Not in the flow path: {', '.join(off)}")
    caption = "".join(
        f'<div style="font-size:12px;color:{_MUTED};margin-top:4px">{escape(n)}</div>'
        for n in notes
    )
    return (
        f'<div class="cadetgui-system-diagram">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Flow path of the LC system" '
        f'style="width:100%;max-width:{width:.0f}px;height:auto;display:block" '
        f'font-family="var(--cg-font, system-ui, sans-serif)">'
        f"{''.join(parts)}</svg>{caption}</div>"
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
        carries: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> None:
        """Redraw for `flow_sheet` (a built LCFlowSheet, or `None` while inputs are invalid)."""
        if flow_sheet is None:
            note = "No system to show while inputs are invalid."
            self.root.value = f'<em style="color:{_MUTED}">{note}</em>'
            return
        self.root.value = render_system_svg(flow_sheet.units_dict, bypassed, inlets, carries)
