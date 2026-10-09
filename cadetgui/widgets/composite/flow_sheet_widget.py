from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Dict, List, Optional, Tuple

import ipywidgets as W
from CADETProcess.processModel import Cstr, Inlet, Outlet, TubularReactor
from CADETProcess.processModel.unitOperation import ChromatographicColumnBase

from .._chrome import style_tag
from ..elements import ChoiceField
from ._pid_symbols import FG, MUTED, MUTED_STROKE, load_symbol
from .system_diagram import _PORTS, _caption, _marker, _symbol, _tube, _wire
from .unit_operation_widget import UnitOperationWidget

__all__ = ["FlowSheetWidget", "render_flow_sheet_svg"]

_MARGIN = 16
_GAP = 70
_ROW = 70
_BOX = (130.0, 60.0)
_TUBE_LENGTH = 90.0
_LEAD = 16
WARN = "var(--cg-warn, #a16207)"


@dataclass
class _Node:
    unit: Any
    symbol: Optional[str]
    width: float
    up: float
    down: float
    in_x: float
    out_x: float
    x: float = 0.0
    y: float = 0.0


def _node(unit: Any) -> _Node:
    if isinstance(unit, ChromatographicColumnBase):
        name = "Column"
    elif isinstance(unit, Inlet):
        name = "Inlet"
    elif isinstance(unit, Outlet):
        name = "Outlet"
    elif isinstance(unit, Cstr):
        name = "Mixer"
    elif isinstance(unit, TubularReactor):
        return _Node(unit, None, _TUBE_LENGTH, 0.0, 0.0, 0.0, _TUBE_LENGTH)
    else:
        w, h = _BOX
        return _Node(unit, None, w, h / 2, h / 2, 0.0, w)
    sym = load_symbol(name)
    in_x, out_x, port_y = _PORTS[name]
    return _Node(unit, name, sym.width, port_y, sym.height - port_y, in_x, out_x)


def _edges(flow_sheet: Any) -> List[Tuple[Any, Any]]:
    edges = []
    for origin, entry in flow_sheet.connections.items():
        for destinations in (entry["destinations"] or {}).values():
            edges.extend((origin, destination) for destination in destinations)
    return list(dict.fromkeys(edges))


def _layers(units: List[Any], edges: List[Tuple[Any, Any]]) -> Dict[Any, int]:
    """Longest-path layer of every unit; edges closing a cycle are ignored."""
    successors: Dict[Any, List[Any]] = {u: [] for u in units}
    for origin, destination in edges:
        successors[origin].append(destination)
    order: List[Any] = []
    state: Dict[Any, int] = {}
    forward = set()

    def visit(unit: Any) -> None:
        state[unit] = 1
        for nxt in successors[unit]:
            if state.get(nxt) is None:
                forward.add((unit, nxt))
                visit(nxt)
            elif state[nxt] == 2:
                forward.add((unit, nxt))
        state[unit] = 2
        order.append(unit)

    has_origin = {d for _, d in edges}
    for unit in [u for u in units if u not in has_origin] + units:
        if state.get(unit) is None:
            visit(unit)

    layer = {u: 0 for u in units}
    for unit in reversed(order):
        for nxt in successors[unit]:
            if (unit, nxt) in forward:
                layer[nxt] = max(layer[nxt], layer[unit] + 1)

    # Unconnected units are lined up after the connected ones, in the order they were added.
    connected = {u for edge in edges for u in edge}
    first_free = max((layer[u] for u in connected), default=-1) + 1
    for offset, unit in enumerate(u for u in units if u not in connected):
        layer[unit] = first_free + offset
    return layer


def render_flow_sheet_svg(flow_sheet: Any) -> str:
    """Draw the units and connections of any CADET-Process FlowSheet, left to right."""
    units = list(flow_sheet.units)
    if not units:
        return f'<em style="color:{MUTED}">The flow sheet has no units yet.</em>'
    edges = _edges(flow_sheet)
    layer = _layers(units, edges)
    nodes = {u: _node(u) for u in units}

    columns: Dict[int, List[_Node]] = {}
    for unit in units:
        columns.setdefault(layer[unit], []).append(nodes[unit])

    # Units in the same row share one flow line, so straight connections stay straight.
    caption_h = 3 * _LEAD + 8
    n_rows = max(len(c) for c in columns.values())
    up = [max(c[r].up for c in columns.values() if r < len(c)) for r in range(n_rows)]
    down = [max(c[r].down for c in columns.values() if r < len(c)) for r in range(n_rows)]
    row_y = []
    y = _MARGIN
    for r in range(n_rows):
        row_y.append(y + up[r])
        y = row_y[r] + down[r] + caption_h + _ROW
    bottom = y - _ROW

    x = _MARGIN
    for index in sorted(columns):
        column = columns[index]
        width = max(n.width for n in column)
        for r, node in enumerate(column):
            node.x = x + (width - node.width) / 2
            node.y = row_y[r]
        x += width + _GAP
    width = x - _GAP + _MARGIN

    parts = [_marker("cg-arrow", FG), _marker("cg-arrow-muted", MUTED_STROKE)]
    loop_y = bottom + 12
    for origin, destination in edges:
        a, b = nodes[origin], nodes[destination]
        x1, y1 = a.x + a.out_x, a.y
        x2, y2 = b.x + b.in_x, b.y
        if layer[destination] > layer[origin]:
            xm = x2 - _GAP / 2
            d = f"M{x1:g} {y1:g} H{xm:g} V{y2:g} H{x2:g}"
        else:
            d = f"M{x1:g} {y1:g} h12 V{loop_y:g} H{x2 - 12:g} V{y2:g} H{x2:g}"
            loop_y += 10
        parts.append(_wire(d))
    bottom = max(bottom, loop_y)

    for node in nodes.values():
        cx = node.x + node.width / 2
        if isinstance(node.unit, Cstr):
            symbol = _symbol(node.symbol, node.x, node.y - node.up)
            parts.append(symbol.replace(">Mixer<", ">CSTR<"))
        elif node.symbol is not None:
            parts.append(_symbol(node.symbol, node.x, node.y - node.up))
        elif isinstance(node.unit, TubularReactor):
            parts.append(_tube(node.x, node.x + node.width, node.y))
        else:
            w, h = _BOX
            parts.append(
                f'<rect x="{node.x:g}" y="{node.y - h / 2:g}" width="{w:g}" height="{h:g}" '
                f'rx="6" fill="none" style="stroke: {FG}" stroke-width="1.5"/>'
            )
        top = node.y + node.down + 18
        parts.append(_caption([node.unit.name], cx, top, strong=True))
        parts.append(_caption([type(node.unit).__name__], cx, top + _LEAD))
        missing = len(getattr(node.unit, "missing_parameters", []))
        if missing:
            label = f"{missing} missing parameter{'s' if missing > 1 else ''}"
            parts.append(
                f'<text x="{cx:g}" y="{top + 2 * _LEAD:g}" text-anchor="middle" font-size="14" '
                f'style="fill: {WARN}">{label}</text>'
            )

    height = bottom + _MARGIN
    return (
        f'<div class="cadetgui-system-diagram">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Flow sheet {escape(str(flow_sheet.name))}" '
        f'style="width:100%;max-width:{width:.0f}px;height:auto;display:block" '
        f'font-family="var(--cg-font, system-ui, sans-serif)">'
        f'{"".join(parts)}</svg></div>'
    )


class FlowSheetWidget:
    """Read-only diagram of a CADET-Process FlowSheet, with a chosen unit's view below it.

    Units with missing parameters are marked in the diagram.
    """

    def __init__(self, flow_sheet: Any) -> None:
        self.flow_sheet = flow_sheet
        self.diagram = W.HTML()
        self.unit_picker = ChoiceField(label="Unit:", options=[])
        self.unit_view: Optional[UnitOperationWidget] = None
        self._panel = W.VBox()
        self.root = W.VBox([W.HTML(style_tag()), self.diagram, self.unit_picker, self._panel])
        self.unit_picker.observe(lambda _change: self._show_unit(), names="selected_index")
        self.refresh()

    def refresh(self) -> None:
        """Redraw, e.g. after units, connections or parameters were changed in code."""
        self.diagram.value = render_flow_sheet_svg(self.flow_sheet)
        units = list(self.flow_sheet.units)
        selected = self.unit_picker.value
        self.unit_picker.set_options([(u.name, u) for u in units], keep_value=True)
        if selected not in units and units:
            missing = [u for u in units if u.missing_parameters]
            self.unit_picker.value = (missing or units)[0]
        self.unit_picker.layout.display = "" if units else "none"
        self._show_unit()

    def _show_unit(self) -> None:
        unit = self.unit_picker.value
        self.unit_view = None if unit is None else UnitOperationWidget(unit)
        self._panel.children = [] if self.unit_view is None else [self.unit_view.root]

    def get_value(self) -> Any:
        """Return the FlowSheet this widget shows."""
        return self.flow_sheet

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
