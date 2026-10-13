from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Collection, List, Mapping, Optional, Sequence, Tuple

import ipywidgets as W

from ...instrument.system import BYPASSABLE_UNITS, UNIT_LABELS
from ...io.configuration_store import ConfigurationState, InstrumentState
from .svg import (
    CAPTION_FONT,
    CAPTION_LEAD,
    FG,
    MUTED,
    MUTED_STROKE,
    PORTS,
    SURFACE,
    arrow_marker,
    flow_line,
    load_symbol,
    num,
    place_symbol,
    text_block,
    tube_segment,
)

__all__ = ["SystemDiagram", "render_system_svg", "recipe_diagram_svg", "HARDWARE_ONLY_NOTE"]

HARDWARE_ONLY_NOTE = (
    "How each run uses this hardware (which inlets pump, when the loop injects, which "
    "units are bypassed) is set by its experiment type — see the measurement."
)

ACCENT = "var(--cg-primary, #005b82)"

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

_LOOP_IN_Y = 145.5
_LOOP_SAMPLE_PORT = (152.8, 80.5)
_STEM = (30.5, 95.5)
_FEED_RISE = PORTS["SampleLoop"][2] - _LOOP_SAMPLE_PORT[1] + PORTS["Inlet"][2]

_GAP = 28
_TUBE = 80
_MARGIN = 16
_BUS = 30
_INLET_GAP = 40
_ROW_DROP = 40
_HALO_PAD = 5
_OBSERVE_STEM = 14
_OBSERVE_GAP = 6
_COMPACT_MAX_WIDTH = 560


def _lines(label: str) -> List[str]:
    head, sep, tail = label.partition(" (")
    return [head, f"({tail}"] if sep else [label]


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
        width = 2 * load_symbol("UVSensor").width + 3 * 20
        return _Item(unit, state, x, width, 0, width, _STEM[1] + 2, 0, None)
    if unit.startswith("tubing"):
        return _Item(unit, state, x, _TUBE, 0, _TUBE, 0, 0, None)
    name = _SYMBOL_OF[unit]
    sym = load_symbol(name)
    in_x, out_x, port_y = PORTS[name]
    return _Item(
        unit, state, x, sym.width, in_x, out_x, port_y, sym.height - port_y, name
    )


def _label_of(unit: str) -> str:
    return UNIT_LABELS.get(unit, unit.capitalize())


def _extent(it: _Item, note: str, sub: Sequence[str] = ()) -> Tuple[float, float]:
    """Return how far the item, captions included, reaches above and below the flow line."""
    label_lines = len(_lines(_label_of(it.unit)))
    if it.unit == "tubing_detectors":
        return it.up, 20 + (label_lines - 1) * CAPTION_LEAD + 6
    if it.symbol is None:
        return 12 + label_lines * CAPTION_LEAD, 0
    up, down = it.up, it.down
    if note:
        up += 6 + CAPTION_FONT
    if _label_of(it.unit) != load_symbol(it.symbol).text:
        down += 8 + label_lines * CAPTION_LEAD
    if sub:
        down += len(sub) * CAPTION_LEAD + (0 if down > it.down else 8)
    return up, down


def _draw_item(it: _Item, my: float, note: str, sub: Sequence[str] = ()) -> str:
    label = _label_of(it.unit)
    lines = _lines(label)
    cx = it.x + it.width / 2

    if it.unit == "tubing_detectors":
        sensor_w = load_symbol("UVSensor").width
        parts = [tube_segment(it.x, it.x + it.width, my)]
        for name, dx in (("UVSensor", 20), ("CondSensor", 40 + sensor_w)):
            parts.append(place_symbol(name, it.x + dx, my - _STEM[1]))
            parts.append(
                f'<circle cx="{num(it.x + dx + _STEM[0])}" cy="{num(my)}" r="4" '
                f'style="fill: {SURFACE}; stroke: {FG}" stroke-width="1"/>'
            )
        parts.append(text_block(lines, cx, my + 20))
        return "".join(parts)

    if it.symbol is None:
        first = my - 12 - (len(lines) - 1) * CAPTION_LEAD
        return tube_segment(it.x, it.x + it.width, my) + text_block(lines, cx, first)

    sym = load_symbol(it.symbol)
    sy = my - PORTS[it.symbol][2]
    inner = place_symbol(it.symbol, it.x, sy)
    if it.state == "bypassed":
        parts = [
            f'<g opacity="0.4">{inner}</g>',
            f'<rect x="{num(it.x)}" y="{num(sy)}" width="{num(sym.width)}" '
            f'height="{num(sym.height)}" rx="4" fill="none" style="stroke: {MUTED_STROKE}" '
            f'stroke-width="1.5" stroke-dasharray="5 4"/>',
        ]
    else:
        parts = [inner]
    if note:
        parts.append(text_block([note], cx, sy - 6, italic=True))
    below = sy + sym.height + 16
    if label != sym.text:
        parts.append(text_block(lines, cx, below))
        below += len(lines) * CAPTION_LEAD
    if sub:
        parts.append(text_block(list(sub), cx, below))
    return "".join(parts)


def _unit_group(unit: str, state: str, content: str, *, highlighted: bool = False) -> str:
    flag = ' data-highlight="true"' if highlighted else ""
    return f'<g data-unit="{unit}" data-state="{state}"{flag}>{content}</g>'


def _halo_box(it: _Item, my: float) -> Tuple[float, float, float, float]:
    """Bounding box (x, y, width, height) an accent halo wraps around `it`."""
    pad = _HALO_PAD
    if it.symbol is not None:
        sym = load_symbol(it.symbol)
        sy = my - PORTS[it.symbol][2]
        return it.x - pad, sy - pad, sym.width + 2 * pad, sym.height + 2 * pad
    if it.unit == "tubing_detectors":
        top = my - it.up
        return it.x - pad, top - pad, it.width + 2 * pad, it.up + 2 * pad
    return it.x - pad, my - 6 - pad, it.width + 2 * pad, 12 + 2 * pad


def _halo(it: _Item, my: float) -> str:
    x, y, w, h = _halo_box(it, my)
    return (
        f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="8" '
        f'fill="none" style="stroke: {ACCENT}" stroke-width="3"/>'
    )


def _observe_extent() -> float:
    """Height of the lane above the drawing that holds the "measured here" label."""
    return _OBSERVE_GAP + CAPTION_FONT + 8


def _observe_marker(x: float, y: float, tip: float, label_x: float) -> str:
    """Pin from the outlet at (`x`, `y`) up to `tip`, labelled in the lane above it."""
    dot = (
        f'<circle cx="{num(x)}" cy="{num(tip)}" r="4.5" '
        f'style="fill: {ACCENT}; stroke: {SURFACE}" stroke-width="1.5"/>'
    )
    return (
        f'<path d="M{num(x)} {num(y)} V{num(tip)}" style="stroke: {ACCENT}" stroke-width="2"/>'
        f"{dot}" + text_block(["measured here"], label_x, tip - _OBSERVE_GAP - 2, italic=True)
    )


def _dim(content: str, on: bool) -> str:
    return content if on else f'<g opacity="0.4">{content}</g>'


_WRAP = 18
_CHAR_W = 7.4


def _names(names: Sequence[str]) -> List[str]:
    """Wrap component names onto short lines, in parentheses."""
    lines: List[str] = []
    for name in names:
        if lines and len(lines[-1]) + len(name) + 2 <= _WRAP:
            lines[-1] += f", {name}"
        else:
            lines.append(name)
    if len(lines) > 3:
        return [f"({len(names)} components)"]
    lines = [f"{line}," for line in lines[:-1]] + lines[-1:]
    lines[0] = f"({lines[0]}"
    lines[-1] = f"{lines[-1]})"
    return lines


def _text_width(lines: Sequence[str]) -> float:
    return max((len(line) for line in lines), default=0) * _CHAR_W


def _inlet_lines(unit: str, on: bool, carries: Optional[Mapping[str, Sequence[str]]]) -> List[str]:
    if unit == "feed_inlet":
        head = ["Feed inlet", "(sample components)"]
        names = (carries or {}).get(unit)
        if not on:
            return [*head, "unused"]
        return [*head, *_names(names)] if names else head
    label = _label_of(unit)
    if not on:
        return [label, "(unused)"]
    if carries is None or unit not in carries:
        return [label]
    return [label, *(_names(carries[unit]) if carries[unit] else ["(buffer only)"])]


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
    equilibration: Collection[str] = (),
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
    eq = [b for b in _BUFFERS if b in equilibration and b in inlets]
    on = [b for b in _BUFFERS if b in inlets and b not in eq]
    if eq:
        via = " through the mixer" if mixer_on else ""
        lead = f"The system starts pre-equilibrated with buffer {_letters(eq)}{via}"
        follow = f"; at t=0 the flow switches to buffer {_letters(on)}" if on else ""
        notes.append(f"{lead}{follow}.")
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
    equilibration: Collection[str] = (),
    column_model: Optional[str] = None,
    *,
    highlight: Collection[str] = (),
    observe: Optional[str] = None,
    compact: bool = False,
    hardware_only: bool = False,
) -> str:
    """Render the LC flow path from the P&ID symbols as an HTML fragment holding one SVG.

    `units` are the unit names present in the flow sheet; `bypassed` the ones the user
    excluded. Bypassed units are left out of the path (the mixer, which always stays as the
    buffer junction, is drawn dimmed and dashed). `inlets` are the inlet units the process
    drives; `None` means unknown, drawn as one generic inlet. Every buffer inlet and the feed
    inlet of the flow sheet is drawn, the ones outside `inlets` dimmed and marked unused.
    `carries` maps an inlet (and `"sample_loop"`) to the component names it delivers and adds
    them to the labels (the sample loop's under its symbol) and to a plain-language caption
    under the drawing. `column_model` is captioned under the column symbol.

    `highlight` marks units an accent halo and `data-highlight="true"`, and lists their
    labels in a "Characterized here" caption. `observe` draws a "measured here" marker at
    that unit's outlet (`data-observe`); if the unit isn't drawn, a caption says so instead.
    `compact` drops the inlet stack and general captions (highlight/observe captions stay)
    and scales the drawing down for use in a small card.

    `hardware_only` draws every installed inlet plainly (`inlets`, `carries` and
    `equilibration` are ignored) and replaces the usage captions by `HARDWARE_ONLY_NOTE`.
    """
    units = set(units)
    if hardware_only and not compact:
        inlets = [u for u in (*_BUFFERS, "feed_inlet") if u in units]
        carries, equilibration = None, ()
    bypassed = set(bypassed)
    highlight = set(highlight)
    path = [u for u in _MAIN_PATH if u in units]
    has_loop = "sample_loop" in path
    known = inlets is not None and not compact
    active = set(inlets or ())
    if known:
        buffers = [b for b in _BUFFERS if b in units or b in active]
        active_buffers = [b for b in buffers if b in active]
    elif compact:
        buffers = active_buffers = []
    else:
        buffers = active_buffers = ["inlet"]
    feed_shown = known and ("feed_inlet" in units or "feed_inlet" in active)
    feed_on = feed_shown and "feed_inlet" in active
    inlet_sym = load_symbol("Inlet")
    feed_lines = _inlet_lines("feed_inlet", feed_on, carries if known else None)
    feed_extra = (len(feed_lines) - 1) * CAPTION_LEAD
    feed_width = _text_width(feed_lines)

    buffer_lines = {
        b: (_inlet_lines(b, b in active_buffers, carries) if known else _lines(_label_of(b)))
        for b in buffers
    }
    pitches = [
        inlet_sym.height + max(_INLET_GAP, 8 + len(buffer_lines[b]) * CAPTION_LEAD)
        for b in buffers
    ]
    stack_h = max(sum(pitches) - _INLET_GAP, 0)
    heading = 24 if known and buffers else 0
    column_w = max(
        [inlet_sym.width, *(_text_width(lines) for lines in buffer_lines.values())]
    )
    symbol_x = _MARGIN + (column_w - inlet_sym.width) / 2
    x0 = _MARGIN + (column_w + _BUS + 25 if buffers else 0)

    items: List[_Item] = []
    x = x0
    for unit in path:
        state = "bypassed" if unit == "mixer" and "mixer" in bypassed else "active"
        it = _item(unit, x, state)
        items.append(it)
        x += it.width + _GAP

    up_max = stack_h / 2 + 4 + heading
    if feed_shown and has_loop:
        up_max = max(up_max, _FEED_RISE + 6 + feed_extra + CAPTION_FONT)

    def sub_lines(unit: str) -> List[str]:
        if unit == "column" and column_model:
            return [column_model]
        if unit == "sample_loop" and known and carries and carries.get("sample_loop"):
            return _names(carries["sample_loop"])
        return []

    item_down = 0.0
    for it in items:
        sub = sub_lines(it.unit)
        up, down = _extent(it, "bypassed" if it.state == "bypassed" else "", sub)
        up_max, item_down = max(up_max, up), max(item_down, down)
    observe_lane = _observe_extent() if any(it.unit == observe for it in items) else 0.0
    my = _MARGIN + observe_lane + up_max

    junction = next((it for it in reversed(items) if it.unit in _JUNCTIONS), None)
    target = next((it for it in items if it.unit not in _JUNCTIONS), None)
    row2_y = my + item_down + _ROW_DROP
    parts = [arrow_marker("cg-arrow", FG), arrow_marker("cg-arrow-muted", MUTED_STROKE)]
    right = x - _GAP

    first = items[0] if items else None
    bus_x = _MARGIN + column_w + _BUS
    if buffers and first is not None:
        top = my - stack_h / 2
        if known:
            head = text_block(
                ["Buffers via mixer"], _MARGIN, top - 12, start=True, strong=bool(active_buffers)
            )
            parts.append(head)
        ys = {}
        for i, buf in enumerate(buffers):
            y = top + sum(pitches[:i])
            on = buf in active_buffers
            content = _dim(place_symbol(_SYMBOL_OF[buf], symbol_x, y), on)
            lines = buffer_lines[buf]
            if known or _label_of(buf) != load_symbol(_SYMBOL_OF[buf]).text:
                content += text_block(
                    lines, symbol_x + inlet_sym.width / 2, y + inlet_sym.height + 16
                )
            parts.append(_unit_group(buf, "active" if on else "unused", content))
            ys[buf] = y + PORTS["Inlet"][2]
            parts.append(
                flow_line(
                    f"M{num(symbol_x + inlet_sym.width - 0.5)} {num(ys[buf])} H{num(bus_x)}",
                    arrow=False,
                    muted=not on,
                )
            )
        on_ys = [ys[b] for b in active_buffers] + [my]
        all_ys = list(ys.values()) + [my]
        if max(all_ys) > min(all_ys) and len(active_buffers) < len(buffers):
            parts.append(
                flow_line(f"M{num(bus_x)} {num(min(all_ys))} V{num(max(all_ys))}",
                      arrow=False, muted=True)
            )
        if active_buffers and max(on_ys) > min(on_ys):
            parts.append(
                flow_line(f"M{num(bus_x)} {num(min(on_ys))} V{num(max(on_ys))}", arrow=False)
            )
        parts.append(
            flow_line(
                f"M{num(bus_x)} {num(my)} H{num(first.x + first.in_x)}",
                muted=not active_buffers,
            )
        )

    for a, b in zip(items, items[1:]):
        x1 = a.x + a.out_x
        if b.unit == "sample_loop":
            x2 = b.x + b.in_x
            y2 = my - (PORTS["SampleLoop"][2] - _LOOP_IN_Y)
            d = f"M{num(x1)} {num(my)} H{num(x2)} V{num(y2)}"
        else:
            d = f"M{num(x1)} {num(my)} H{num(b.x + b.in_x)}"
        parts.append(flow_line(d, arrow=b.symbol is not None))

    observe_drawn = False
    for it in items:
        note = "bypassed" if it.state == "bypassed" else ""
        sub = sub_lines(it.unit)
        is_highlighted = it.unit in highlight
        content = _draw_item(it, my, note, sub)
        if is_highlighted:
            content += _halo(it, my)
        parts.append(_unit_group(it.unit, it.state, content, highlighted=is_highlighted))
        if observe is not None and it.unit == observe:
            ox = it.x + it.out_x
            half = _text_width(["measured here"]) / 2
            label_x = min(max(ox, _MARGIN + half), right + _MARGIN - half)
            marker = _observe_marker(ox, my, my - up_max - 4, label_x)
            parts.append(f'<g data-observe="{escape(observe)}">{marker}</g>')
            observe_drawn = True

    if "waste" in units and junction is not None and not compact:
        cx = junction.x + junction.width / 2
        start = my + junction.down
        wx = cx - inlet_sym.width / 2
        content = place_symbol("Outlet", wx, row2_y)
        label = _label_of("waste")
        content += text_block([label], cx, row2_y + inlet_sym.height + 16)
        parts.append(flow_line(f"M{num(cx)} {num(start)} V{num(row2_y)}", muted=True))
        parts.append(_unit_group("waste", "idle", content))
        right = max(right, wx + inlet_sym.width)

    feed_state = "active" if feed_on else "unused"
    if feed_shown and has_loop:
        loop = next(it for it in items if it.unit == "sample_loop")
        fx = loop.x + loop.width + _GAP
        fy = my - _FEED_RISE
        content = _dim(place_symbol("Inlet", fx, fy), feed_on)
        content += text_block(feed_lines, fx + inlet_sym.width / 2, fy - 6 - feed_extra)
        sample_x = loop.x + _LOOP_SAMPLE_PORT[0]
        parts.append(
            flow_line(
                f"M{num(fx + 0.5)} {num(fy + PORTS['Inlet'][2])} H{num(sample_x)}",
                arrow=False,
                muted=not feed_on,
            )
        )
        parts.append(_unit_group("feed_inlet", feed_state, content))
        right = max(right, fx + inlet_sym.width, fx + (inlet_sym.width + feed_width) / 2)
    elif feed_shown and target is not None:
        column_in = target.x + target.in_x
        cx = target.x + target.width / 2
        fx = cx - inlet_sym.width / 2
        merge_x = column_in - _GAP / 2
        jog_y = row2_y - _ROW_DROP / 2
        content = _dim(place_symbol("Inlet", fx, row2_y), feed_on)
        content += text_block(feed_lines, cx, row2_y + inlet_sym.height + 16)
        parts.append(
            flow_line(
                f"M{num(cx)} {num(row2_y)} V{num(jog_y)} H{num(merge_x)} "
                f"V{num(my)} H{num(column_in)}",
                muted=not feed_on,
            )
        )
        parts.append(_unit_group("feed_inlet", feed_state, content))
        right = max(right, fx + inlet_sym.width, cx + feed_width / 2)

    width = right + _MARGIN
    bottom = max(my + item_down, my + stack_h / 2 + 24 + (CAPTION_LEAD if known else 0))
    if ("waste" in units and junction is not None and not compact) or (
        feed_shown and not has_loop
    ):
        below = row2_y + inlet_sym.height + 24 + (feed_extra if feed_shown and not has_loop else 0)
        bottom = max(bottom, below)
    height = bottom + _MARGIN

    shown = set(buffers) | ({"feed_inlet"} if feed_shown else set())
    notes = (
        _usage_notes(active, carries, shown, path, "mixer" not in bypassed, equilibration)
        if known and not hardware_only
        else []
    )
    off = [UNIT_LABELS[u] for u in _MAIN_PATH if u in bypassed and u in UNIT_LABELS]
    if off:
        notes.append(f"Not in the flow path: {', '.join(off)}")

    lead_notes: List[str] = []
    if highlight:
        ordered = [u for u in _MAIN_PATH if u in highlight]
        ordered += [u for u in dict.fromkeys(highlight) if u not in _MAIN_PATH]
        labels = [UNIT_LABELS.get(u, u) for u in ordered]
        lead_notes.append(f"Characterized here: {', '.join(labels)}")
    if observe is not None and not observe_drawn:
        label = UNIT_LABELS.get(observe, observe)
        lead_notes.append(f"Measured here: {label} (not shown in this diagram).")
    notes = lead_notes + notes
    if hardware_only and not compact:
        notes.append(HARDWARE_ONLY_NOTE)

    caption = "".join(
        f'<div style="font-size:12px;color:{MUTED};margin-top:4px">{escape(n)}</div>'
        for n in notes
    )

    inner = "".join(parts)
    if compact and width > 0:
        scale = min(1.0, _COMPACT_MAX_WIDTH / width)
        if scale < 1.0:
            inner = f'<g transform="scale({scale:.4g})">{inner}</g>'
            width, height = width * scale, height * scale

    return (
        f'<div class="cadetgui-system-diagram">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Flow path of the LC system" '
        f'style="width:100%;max-width:{width:.0f}px;height:auto;display:block" '
        f'font-family="var(--cg-font, system-ui, sans-serif)">'
        f"{inner}</svg>{caption}</div>"
    )


def _recipe_units(instrument: InstrumentState) -> set:
    """Return the unit names an `InstrumentState` builds, mirroring `LCFlowSheet.__init__`.

    Buffers A-D, the feed inlet, mixer, outlet and waste are always present; the
    bypassable tubing/column units are present unless in `bypass_units`, and the
    sample loop is present iff `include_sample_loop`.
    """
    bypass = set(instrument.bypass_units)
    units = {
        "buffer_a", "buffer_b", "buffer_c", "buffer_d",
        "feed_inlet", "mixer", "outlet", "waste",
    }  # fmt: skip
    units.update(u for u in BYPASSABLE_UNITS if u != "mixer" and u not in bypass)
    if instrument.include_sample_loop:
        units.add("sample_loop")
    return units


def recipe_diagram_svg(
    recipe: ConfigurationState,
    *,
    observe: Optional[str] = None,
    highlight: Collection[str] = (),
    compact: bool = True,
) -> str:
    """Render a saved recipe's flow path without building a process or any widget.

    Derives the unit set from `recipe.instrument` the same way `InstrumentWidget` feeds
    `SystemDiagram` (bypass list + sample-loop flag); `instrument is None` (a standalone,
    column-only configuration) renders just the column.
    """
    instrument = recipe.instrument
    if instrument is None:
        return render_system_svg(
            {"column"}, highlight=highlight, observe=observe, compact=compact
        )
    return render_system_svg(
        _recipe_units(instrument),
        set(instrument.bypass_units),
        highlight=highlight,
        observe=observe,
        compact=compact,
    )


class SystemDiagram:
    """Read-only schematic of the current LC flow path.

    With `hardware_only`, the installed hardware is drawn without the inlet usage of the
    current process (see `render_system_svg`).
    """

    def __init__(self, *, hardware_only: bool = False) -> None:
        self.hardware_only = hardware_only
        self._flow_sheet: object = None
        self._bypassed: Collection[str] = ()
        self._inlets: Optional[Sequence[str]] = None
        self._carries: Optional[Mapping[str, Sequence[str]]] = None
        self._equilibration: Collection[str] = ()
        self._column_model: Optional[str] = None
        self._highlight: Collection[str] = ()
        self._observe: Optional[str] = None
        self.root = W.HTML("")
        self.update(None)

    def update(
        self,
        flow_sheet: object,
        bypassed: Collection[str] = (),
        inlets: Optional[Sequence[str]] = None,
        carries: Optional[Mapping[str, Sequence[str]]] = None,
        equilibration: Collection[str] = (),
        column_model: Optional[str] = None,
    ) -> None:
        """Redraw for `flow_sheet` (a built LCFlowSheet, or `None` while inputs are invalid)."""
        self._flow_sheet = flow_sheet
        self._bypassed = bypassed
        self._inlets = inlets
        self._carries = carries
        self._equilibration = equilibration
        self._column_model = column_model
        self._render()

    def set_highlight(self, units: Collection[str], observe: Optional[str] = None) -> None:
        """Mark the units and outlet the currently selected characterization step covers."""
        self._highlight = units
        self._observe = observe
        self._render()

    def _render(self) -> None:
        if self._flow_sheet is None:
            note = "No system to show while inputs are invalid."
            self.root.value = f'<em style="color:{MUTED}">{note}</em>'
            return
        self.root.value = render_system_svg(
            self._flow_sheet.units_dict,
            self._bypassed,
            self._inlets,
            self._carries,
            self._equilibration,
            self._column_model,
            highlight=self._highlight,
            observe=self._observe,
            hardware_only=self.hardware_only,
        )
